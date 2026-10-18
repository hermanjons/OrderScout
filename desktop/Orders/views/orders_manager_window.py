from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
    QListView, QPushButton, QLineEdit, QComboBox,
    QFrame, QSizePolicy,
    QStyleOptionViewItem, QStyle,
    QFormLayout, QStackedWidget, QTableWidget, QHeaderView, QTableWidgetItem,
    QDialog, QScrollArea, QGridLayout, QFileDialog, QLayout
)
from PyQt6.QtCore import Qt, QDate, QTimer, QRegularExpression, QSignalBlocker, pyqtSignal, QAbstractListModel, QModelIndex, QSize, QEvent, QRect, QPoint
from PyQt6.QtGui import QRegularExpressionValidator, QDoubleValidator, QIcon, QPainter, QPen, QFont, QColor, QBrush

from Core.views import (
    SwitchSelectWidget, DateSelector, ActionPulseButton,
    SmoothHeightFrame,
    optimized_table_updates,
    compose_record_workspace_style,
    RecordWorkspaceBehaviorAdapter, RecordWorkspaceListDelegate, RecordWorkspaceListModel, RecordWorkspaceScaffold,
)
from Orders.constants import ui_constants as orders_ui, ui_text
from Core.views.tab_widgets import GlowTabWidget
from Core.threads.sync_worker import SyncWorker
from Core.utils.contact_utils import extract_contact_and_address

from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message

from Orders.constants import (
    ORDERS_ENTITY_EMPTY_TEMPLATE,
    ORDERS_ENTITY_LOADING_TEMPLATE,
    ORDERS_LIST_CARD_BG_COLOR,
    ORDERS_LIST_CARD_HOVER_BG_COLOR,
    ORDERS_LIST_CARD_HOVER_BORDER_COLOR,
    ORDERS_LIST_CARD_ICON_PLACEHOLDER_COLOR,
    ORDERS_LIST_CARD_META_KEY_COLOR,
    ORDERS_LIST_CARD_META_VALUE_COLOR,
    ORDERS_LIST_CARD_MUTED_VALUE_COLOR,
    ORDERS_LIST_CARD_OVERDUE_BG_COLOR,
    ORDERS_LIST_CARD_OVERDUE_BORDER_COLOR,
    ORDERS_LIST_CARD_SELECTED_BG_COLOR,
    ORDERS_LIST_CARD_SELECTED_BORDER_COLOR,
    ORDERS_LIST_CARD_SPIN_BORDER_COLOR,
    ORDERS_LIST_CARD_TITLE_COLOR,
    ORDERS_LIST_DEADLINE_BADGE_OK_BORDER_COLOR,
    ORDERS_LIST_DEADLINE_BADGE_OK_FILL_COLOR,
    ORDERS_LIST_DEADLINE_BADGE_OK_TEXT_COLOR,
    ORDERS_LIST_DEADLINE_BADGE_OVERDUE_BORDER_COLOR,
    ORDERS_LIST_DEADLINE_BADGE_OVERDUE_FILL_COLOR,
    ORDERS_LIST_DEADLINE_BADGE_OVERDUE_TEXT_COLOR,
    ORDERS_LIST_DELEGATE_HOOK_HEIGHT,
    ORDERS_LIST_DELEGATE_HOOK_WIDTH,
    ORDERS_LIST_DELEGATE_ICON_SIZE,
    ORDERS_LIST_DELEGATE_ROW_HEIGHT,
    ORDERS_LIST_EMPTY_TEXT,
    ORDERS_LIST_FONT_FAMILY,
    ORDERS_LIST_BADGE_FONT_SIZE,
    ORDERS_LIST_META_FONT_SIZE,
    ORDERS_LIST_PLACEHOLDER_FONT_SIZE,
    ORDERS_LIST_PLACEHOLDER_TEXT_COLOR,
    ORDERS_LIST_SEGMENT_SEPARATOR_COLOR,
    ORDERS_LIST_TITLE_FONT_SIZE,
    ORDERS_SIDEBAR_BULK_TOOLTIP,
    ORDERS_SIDEBAR_EDIT_TOOLTIP,
    ORDERS_STYLE,
    ORDERS_WINDOW_MIN_HEIGHT,
    ORDERS_WINDOW_MIN_WIDTH,
    ORDERS_WINDOW_X,
    ORDERS_WINDOW_Y,
    ORDERS_WORKSPACE_LEFT_COLLAPSE_TRIGGER,
    ORDERS_WORKSPACE_LEFT_STICK_SIZE,
    ORDERS_WORKSPACE_PAGE_SIZE_OPTIONS,
    ORDERS_WORKSPACE_SHELL_KWARGS,
)
from Orders.constants.paths import (
    ORDERS_MANAGER_ICON_PATH,
    ORDERS_SIDEBAR_BULK_ICON_PATH,
    ORDERS_SIDEBAR_EDIT_ICON_PATH,
)
from Orders.signals.signals import order_signals


def _orders_action(name: str):
    from Orders.views import actions

    return getattr(actions, name)


def approve_return_claim(*args, **kwargs):
    return _orders_action("approve_return_claim")(*args, **kwargs)


def load_ready_to_ship_orders(*args, **kwargs):
    return _orders_action("load_ready_to_ship_orders")(*args, **kwargs)


def load_orders_for_source_filters(*args, **kwargs):
    return _orders_action("load_orders_for_source_filters")(*args, **kwargs)


def load_orders_for_status_filter(*args, **kwargs):
    return _orders_action("load_orders_for_status_filter")(*args, **kwargs)


def load_orders_by_numbers(*args, **kwargs):
    return _orders_action("load_orders_by_numbers")(*args, **kwargs)


def load_returns_for_source_filters(*args, **kwargs):
    return _orders_action("load_returns_for_source_filters")(*args, **kwargs)


def load_returns_from_db(*args, **kwargs):
    return _orders_action("load_returns_from_db")(*args, **kwargs)


def load_order_items_for_order_number(*args, **kwargs):
    return _orders_action("load_order_items_for_order_number")(*args, **kwargs)


def load_order_items_for_order_numbers(*args, **kwargs):
    return _orders_action("load_order_items_for_order_numbers")(*args, **kwargs)


def load_order_profit_catalog(*args, **kwargs):
    return _orders_action("load_order_profit_catalog")(*args, **kwargs)


def estimate_order_profit(*args, **kwargs):
    return _orders_action("estimate_order_profit")(*args, **kwargs)


def write_order_profit_payload_to_excel(*args, **kwargs):
    return _orders_action("write_order_profit_payload_to_excel")(*args, **kwargs)


def format_order_summary(*args, **kwargs):
    return _orders_action("format_order_summary")(*args, **kwargs)


def format_order_status(*args, **kwargs):
    return _orders_action("format_order_status")(*args, **kwargs)


def summarize_order_shipping_deadline(*args, **kwargs):
    return _orders_action("summarize_order_shipping_deadline")(*args, **kwargs)


def refresh_cargo_filter(*args, **kwargs):
    return _orders_action("refresh_cargo_filter")(*args, **kwargs)


def refresh_order_status_filter(*args, **kwargs):
    return _orders_action("refresh_order_status_filter")(*args, **kwargs)


def start_filter_worker(*args, **kwargs):
    return _orders_action("start_filter_worker")(*args, **kwargs)


def order_platform_filter_options(*args, **kwargs):
    return _orders_action("order_platform_filter_options")(*args, **kwargs)


def list_changeable_cargo_providers(*args, **kwargs):
    return _orders_action("list_changeable_cargo_providers")(*args, **kwargs)


def cargo_provider_code_for_name(*args, **kwargs):
    return _orders_action("cargo_provider_code_for_name")(*args, **kwargs)


def resolve_order_platform_code(*args, **kwargs):
    return _orders_action("resolve_order_platform_code")(*args, **kwargs)


def change_order_cargo_provider(*args, **kwargs):
    return _orders_action("change_order_cargo_provider")(*args, **kwargs)


def change_orders_cargo_provider_bulk(*args, **kwargs):
    return _orders_action("change_orders_cargo_provider_bulk")(*args, **kwargs)


ORDER_ITEMS_CACHE_LIMIT = 100
ORDER_PROFIT_WIDGET_W = 204
ORDER_PROFIT_WIDGET_H = 48


@contextmanager
def _signals_blocked(*widgets):
    blockers: list[object] = []
    previous_states: list[object] = []
    qt_blocker = object()
    try:
        for widget in widgets:
            try:
                blockers.append(QSignalBlocker(widget))
                previous_states.append(qt_blocker)
            except TypeError:
                previous = widget.blockSignals(True)
                blockers.append(widget)
                previous_states.append(previous)
        yield
    finally:
        for blocker, previous in reversed(list(zip(blockers, previous_states))):
            if previous is qt_blocker:
                try:
                    blocker.unblock()
                except Exception:
                    pass
            else:
                try:
                    blocker.blockSignals(previous if isinstance(previous, bool) else False)
                except Exception:
                    pass


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _amount_text(value: Any) -> str:
    try:
        return f"{float(value):.2f} TL"
    except Exception:
        return "-"


def _delta_text(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    if number > 0:
        return f"-{number:.2f} TL"
    if number < 0:
        return f"+{abs(number):.2f} TL"
    return "0.00 TL"


# ============================================================
 # 1. OrdersListWidget - Sipariş Listeleme Bileşeni
# ============================================================

class OrdersListModel(QAbstractListModel):
    TitleRole = RecordWorkspaceListModel.TitleRole
    SubtitleRole = RecordWorkspaceListModel.SubtitleRole
    ExtraRole = RecordWorkspaceListModel.ExtraRole
    IconRole = RecordWorkspaceListModel.IconRole
    OrderRole = RecordWorkspaceListModel.RecordRole
    SelectedRole = RecordWorkspaceListModel.SelectedRole
    PlaceholderRole = RecordWorkspaceListModel.PlaceholderRole
    ActiveRole = RecordWorkspaceListModel.ActiveRole

    def __init__(
        self,
        items: list | None = None,
        parent=None,
        *,
        on_selection_changed=None,
        empty_placeholder_text: str = ORDERS_LIST_EMPTY_TEXT,
    ):
        super().__init__(parent)
        self._items: list[dict] = []
        self._has_placeholder = False
        self._on_selection_changed = on_selection_changed
        self._active_row: int = -1
        self._empty_placeholder_text = str(empty_placeholder_text or ORDERS_LIST_EMPTY_TEXT)
        self._row_by_key: dict[str, int] = {}
        self.set_orders(items or [])

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
        if item.get("placeholder"):
            if role in (Qt.ItemDataRole.DisplayRole, self.TitleRole):
                return item.get("title") or ""
            if role == self.PlaceholderRole:
                return True
            return None

        if role in (Qt.ItemDataRole.DisplayRole, self.TitleRole):
            return item.get("title") or ""
        if role == self.SubtitleRole:
            return item.get("subtitle") or ""
        if role == self.ExtraRole:
            return item.get("extra") or ""
        if role == self.IconRole:
            return item.get("logo_path") or ""
        if role == self.OrderRole:
            return item.get("order")
        if role == self.SelectedRole:
            order = item.get("order")
            return bool(getattr(order, "_selected", False))
        if role == self.PlaceholderRole:
            return False
        if role == self.ActiveRole:
            return row == self._active_row
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        item = self._items[index.row()] if 0 <= index.row() < len(self._items) else {}
        if item.get("placeholder"):
            return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled

    def set_orders(self, orders: list):
        if orders:
            new_items = [self._build_item(o) for o in orders]
            if (
                not self._has_placeholder
                and len(new_items) == len(self._items)
                and [self._item_key(item) for item in new_items] == [self._item_key(item) for item in self._items]
            ):
                self._items = new_items
                self._rebuild_row_lookup()
                if new_items:
                    self.dataChanged.emit(
                        self.index(0),
                        self.index(len(new_items) - 1),
                        [
                            self.TitleRole,
                            self.SubtitleRole,
                            self.ExtraRole,
                            self.IconRole,
                            self.OrderRole,
                            self.SelectedRole,
                            self.ActiveRole,
                        ],
                    )
                return

        self.beginResetModel()
        self._active_row = -1
        self._row_by_key = {}
        if orders:
            self._items = new_items
            self._has_placeholder = False
            self._rebuild_row_lookup()
        else:
            self._items = [{"placeholder": True, "title": self._empty_placeholder_text}]
            self._has_placeholder = True
        self.endResetModel()

    @staticmethod
    def _item_lookup_keys(item: dict) -> tuple[str, ...]:
        order = item.get("order") if isinstance(item, dict) else None
        if order is None:
            return tuple()
        keys: list[str] = []
        for attr_name in ("claimId", "claimNumber", "orderNumber", "order_number"):
            value = str(getattr(order, attr_name, "") or "").strip()
            if value and value not in keys:
                keys.append(value)
        return tuple(keys)

    def _rebuild_row_lookup(self) -> None:
        row_by_key: dict[str, int] = {}
        for row, item in enumerate(self._items):
            if not item or item.get("placeholder"):
                continue
            for key in self._item_lookup_keys(item):
                row_by_key.setdefault(key, row)
        self._row_by_key = row_by_key

    def row_for_order_number(self, order_number: str) -> int:
        needle = str(order_number or "").strip()
        if not needle:
            return -1
        return int(self._row_by_key.get(needle, -1))

    def set_active_row(self, row: int) -> None:
        if self._has_placeholder:
            row = -1
        if row < 0 or row >= len(self._items):
            row = -1
        elif self._items[row].get("placeholder"):
            row = -1
        if self._active_row == row:
            return

        prev = self._active_row
        self._active_row = row

        if prev >= 0:
            prev_idx = self.index(prev)
            self.dataChanged.emit(prev_idx, prev_idx, [self.ActiveRole])
        if row >= 0:
            current_idx = self.index(row)
            self.dataChanged.emit(current_idx, current_idx, [self.ActiveRole])

    def clear_active_row(self) -> None:
        self.set_active_row(-1)

    def visible_count(self) -> int:
        return 0 if self._has_placeholder else len(self._items)

    def item_at(self, row: int) -> dict | None:
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def set_selected(self, row: int, selected: bool) -> None:
        item = self.item_at(row)
        if not item or item.get("placeholder"):
            return
        order = item.get("order")
        if order is None:
            return
        setattr(order, "_selected", bool(selected))
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [self.SelectedRole])
        if self._on_selection_changed:
            self._on_selection_changed()

    @staticmethod
    def _item_key(item: dict) -> str:
        order = item.get("order") if isinstance(item, dict) else None
        return str(getattr(order, "orderNumber", getattr(order, "order_number", "")) or "").strip()

    @staticmethod
    def _build_item(order) -> dict:
        display = format_order_summary(order)
        return {
            "order": order,
            "title": display.get("title") or "",
            "subtitle": display.get("subtitle") or "",
            "extra": display.get("extra") or "",
            "logo_path": display.get("logo_path") or "",
            "estimated_profit_text": _safe_str(getattr(order, "_estimated_profit_text", "")) or "-",
            "estimated_profit_ready": bool(getattr(order, "_estimated_profit_ready", False)),
            "estimated_profit": getattr(order, "_estimated_profit_value", None),
        }


def _order_right_side_rects(
    rect: QRect,
    view: QWidget | None,
    *,
    hook_delegate: RecordWorkspaceListDelegate | None = None,
) -> dict[str, QRect]:
    hook_rect = (
        hook_delegate._hook_rect(rect, view)
        if hook_delegate is not None
        else QRect(rect.right() - ORDERS_LIST_DELEGATE_HOOK_WIDTH - 10, rect.center().y() - 15, ORDERS_LIST_DELEGATE_HOOK_WIDTH, 30)
    )
    profit_width = min(ORDER_PROFIT_WIDGET_W, max(156, hook_rect.left() - rect.left() - 130))
    profit_left = max(rect.left() + 110, hook_rect.left() - 12 - profit_width)
    profit_top = rect.bottom() - ORDER_PROFIT_WIDGET_H - 8
    profit_rect = QRect(profit_left, profit_top, max(120, profit_width), ORDER_PROFIT_WIDGET_H)
    return {
        "hook": hook_rect,
        "profit": profit_rect,
    }


class ProfitDetailControl(QWidget):
    detailRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profit_text = "-"
        self._ready = False
        self._profit_value = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.caption = QLabel("Tahmini Kar")
        self.caption.setStyleSheet("font-size: 10px; color: #64748B;")
        self.caption.setFixedHeight(12)

        self.shell = QFrame(self)
        self.shell.setObjectName("OrderProfitField")
        shell_layout = QHBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.value_label = QLabel("-")
        self.value_label.setObjectName("OrderProfitValueLabel")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.value_label.setMargin(0)
        self.value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.detail_btn = QPushButton("Detay")
        self.detail_btn.setObjectName("OrderProfitDetailBtn")
        self.detail_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detail_btn.setMinimumWidth(92)
        self.detail_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.detail_btn.clicked.connect(self.detailRequested.emit)

        shell_layout.addWidget(self.value_label, 1)
        shell_layout.addWidget(self.detail_btn, 1)
        shell_layout.setStretch(0, 11)
        shell_layout.setStretch(1, 5)

        layout.addWidget(self.caption)
        layout.addWidget(self.shell, 1)
        self.setMinimumHeight(ORDER_PROFIT_WIDGET_H)
        self.setStyleSheet(
            """
            QFrame#OrderProfitField {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
            }
            QLabel#OrderProfitValueLabel {
                padding-left: 12px;
                padding-right: 8px;
                font-size: 11px;
                font-weight: 700;
                color: #0F172A;
            }
            QPushButton#OrderProfitDetailBtn {
                border: 0px;
                border-left: 1px solid #E5E7EB;
                background: #F8FAFC;
                color: #0F172A;
                font-size: 11px;
                font-weight: 800;
                border-top-right-radius: 12px;
                border-bottom-right-radius: 12px;
            }
            QPushButton#OrderProfitDetailBtn:hover {
                background: #EFF6FF;
                color: #2563EB;
            }
            QPushButton#OrderProfitDetailBtn:pressed {
                background: #DBEAFE;
            }
            """
        )

    def set_profit(self, text: str, ready: bool, value: Any) -> None:
        self._profit_text = _safe_str(text) or "-"
        self._ready = bool(ready)
        self._profit_value = value
        self.value_label.setText(self._profit_text)
        if not self._ready:
            color = "#94A3B8"
        else:
            try:
                color = "#DC2626" if float(value or 0) < 0 else "#15803D"
            except Exception:
                color = "#0F172A"
        self.value_label.setStyleSheet(
            f"padding-left: 12px; padding-right: 8px; font-size: 11px; font-weight: 700; color: {color};"
        )


class ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ProfitMetricIcon(QWidget):
    def __init__(self, kind: str, accent: str, background: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._accent = QColor(accent)
        self._background = QColor(background)
        self.setFixedSize(64, 64)

    def set_colors(self, *, accent: str, background: str) -> None:
        self._accent = QColor(accent)
        self._background = QColor(background)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.setBrush(QBrush(self._background))
        painter.setPen(QPen(self._accent, 1.2))
        painter.drawEllipse(rect)

        pen = QPen(self._accent, 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = self.width() // 2
        cy = self.height() // 2

        if self._kind == "sale":
            painter.drawLine(cx - 18, cy - 14, cx - 12, cy - 14)
            painter.drawLine(cx - 12, cy - 14, cx - 8, cy + 10)
            painter.drawLine(cx - 7, cy - 5, cx + 18, cy - 5)
            painter.drawLine(cx - 4, cy + 9, cx + 15, cy + 9)
            painter.drawLine(cx + 18, cy - 5, cx + 14, cy + 9)
            painter.setBrush(QBrush(self._accent))
            painter.drawEllipse(cx - 5, cy + 17, 5, 5)
            painter.drawEllipse(cx + 11, cy + 17, 5, 5)
            return

        if self._kind == "cost":
            painter.drawLine(cx, cy - 18, cx + 17, cy - 8)
            painter.drawLine(cx + 17, cy - 8, cx, cy + 2)
            painter.drawLine(cx, cy + 2, cx - 17, cy - 8)
            painter.drawLine(cx - 17, cy - 8, cx, cy - 18)
            painter.drawLine(cx - 17, cy - 8, cx - 17, cy + 12)
            painter.drawLine(cx + 17, cy - 8, cx + 17, cy + 12)
            painter.drawLine(cx - 17, cy + 12, cx, cy + 22)
            painter.drawLine(cx + 17, cy + 12, cx, cy + 22)
            painter.drawLine(cx, cy + 2, cx, cy + 22)
            return

        painter.drawLine(cx - 18, cy + 14, cx - 6, cy + 2)
        painter.drawLine(cx - 6, cy + 2, cx + 4, cy + 8)
        painter.drawLine(cx + 4, cy + 8, cx + 18, cy - 12)
        painter.drawLine(cx + 18, cy - 12, cx + 18, cy - 1)
        painter.drawLine(cx + 18, cy - 12, cx + 7, cy - 12)


class OrderProfitBreakdownWindow(QWidget):
    _DETAIL_ROWS_PER_PAGE = 4
    _MISSING_ROWS_PER_PAGE = 4

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self._order = None
        self._payload: dict[str, Any] = {}
        self._summary_cards: dict[str, dict[str, Any]] = {}
        self._summary_expanded = False
        self._active_detail_tabs: set[str] = set()
        self._export_drawer_visible = False
        self._missing_reasons: list[str] = []
        self._missing_expanded = False
        self._missing_page_index = 0
        self._detail_page_indexes = {
            "sale": 0,
            "cost": 0,
        }
        self._detail_scroll_value: int | None = None
        self._detail_viewport_lock_generation = 0

        self.setObjectName("OrderProfitWindow")
        self.setWindowTitle("Sipariş Tahmini Kar Detayı")
        self.setWindowIcon(QIcon(str(ORDERS_MANAGER_ICON_PATH)))
        self.setMinimumSize(1120, 760)
        self.resize(1360, 860)
        flags = self.windowFlags()
        flags |= Qt.WindowType.WindowMinMaxButtonsHint
        flags |= Qt.WindowType.WindowCloseButtonHint
        flags &= ~Qt.WindowType.WindowContextHelpButtonHint
        self.setWindowFlags(flags)
        self.setStyleSheet(
            """
            QWidget#OrderProfitWindow {
                background: #F7FAFD;
            }
            QFrame#HeroPanel {
                background: transparent;
                border: 0px;
                border-radius: 0px;
            }
            QFrame#SideCard, QFrame#FooterCard {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 18px;
            }
            QFrame#MissingPanel {
                background: #FFFBEB;
                border: 2px solid #F59E0B;
                border-radius: 22px;
            }
            QFrame#MissingPanel:hover {
                background: #FFF7ED;
                border-color: #D97706;
            }
            QFrame#SideStatRow {
                background: #F8FAFC;
                border: 1px solid #E8EEF6;
                border-radius: 16px;
            }
            QFrame#MissingReasonRow {
                background: #FFFFFF;
                border: 1px solid #FDE68A;
                border-radius: 16px;
            }
            QFrame#EquationCard {
                background: transparent;
                border: 0px;
                border-radius: 0px;
            }
            QFrame#ProfitHero {
                background: #ECFDF5;
                border: 2px solid #16A34A;
                border-radius: 28px;
            }
            QFrame#ProfitHero[danger="true"] {
                background: #FEF2F2;
                border-color: #DC2626;
            }
            QFrame#RevealPanel {
                background: transparent;
                border: 0px;
            }
            QFrame#OperatorBadge {
                background: #FFFFFF;
                border: 1px solid #D9E2EC;
                border-radius: 24px;
            }
            QFrame#ExportDrawer {
                background: #FFFFFF;
                border: 1px solid #D9E2EC;
                border-radius: 16px;
            }
            QFrame#EquationMetric {
                background: #FFFFFF;
                border: 1px solid #DDE7F2;
                border-radius: 24px;
            }
            QFrame#EquationMetric[active="true"] {
                border-width: 2px;
            }
            QFrame#InnerDrawer {
                background: rgba(255, 255, 255, 0.84);
                border: 1px solid #E6EDF5;
                border-radius: 18px;
            }
            QFrame#InnerDrawer[kind="sale"] {
                background: #F7FFF9;
                border-top: 3px solid #16A34A;
            }
            QFrame#InnerDrawer[kind="cost"] {
                background: #FFF8F8;
                border-top: 3px solid #DC2626;
            }
            QFrame#LedgerRow {
                background: #FFFFFF;
                border: 1px solid #E5EDF6;
                border-radius: 14px;
            }
            QFrame#LedgerTotalRow {
                background: #F8FAFC;
                border: 1px solid #DDE7F2;
                border-radius: 14px;
            }
            QLabel#LedgerMarker {
                border-radius: 7px;
            }
            QLabel#DialogTitle {
                font-size: 24px;
                font-weight: 900;
                color: #0F172A;
            }
            QLabel#DialogSub {
                font-size: 12px;
                color: #64748B;
            }
            QLabel#SectionTitle {
                font-size: 13px;
                font-weight: 800;
                color: #0F172A;
            }
            QLabel#CardTitle {
                font-size: 11px;
                font-weight: 800;
                color: #475569;
                text-transform: uppercase;
            }
            QLabel#CardValue {
                font-size: 28px;
                font-weight: 900;
                color: #0F172A;
            }
            QLabel#CardNote, QLabel#RowNote, QLabel#SideNote {
                font-size: 11px;
                color: #64748B;
            }
            QLabel#SideStatLabel {
                font-size: 11px;
                font-weight: 700;
                color: #64748B;
            }
            QLabel#MissingReasonText {
                font-size: 12px;
                font-weight: 600;
                color: #475569;
            }
            QLabel#MissingValue {
                color: #B45309;
                font-size: 42px;
                font-weight: 950;
            }
            QLabel#MissingHint {
                color: #64748B;
                font-size: 12px;
                font-weight: 750;
            }
            QLabel#MissingChevron {
                color: #92400E;
                font-size: 28px;
                font-weight: 950;
            }
            QLabel#EquationLabel {
                font-size: 12px;
                font-weight: 900;
                color: #475569;
            }
            QLabel#EquationValue {
                font-size: 34px;
                font-weight: 950;
            }
            QLabel#EquationHint {
                font-size: 12px;
                font-weight: 700;
                color: #64748B;
            }
            QLabel#ProfitValue {
                font-size: 54px;
                font-weight: 950;
            }
            QLabel#FormulaText {
                font-size: 14px;
                font-weight: 800;
                color: #64748B;
            }
            QLabel#DetailValue {
                font-size: 13px;
                font-weight: 900;
                color: #0F172A;
            }
            QLabel#RowTitle {
                font-size: 13px;
                font-weight: 800;
                color: #0F172A;
            }
            QLabel#SideValue {
                font-size: 13px;
                font-weight: 800;
                color: #0F172A;
            }
            QFrame#BreakdownTrack {
                background: #EEF2F7;
                border: 0px;
                border-radius: 7px;
            }
            QFrame#FooterCard {
                background: rgba(255, 255, 255, 0.88);
            }
            QPushButton#PrimaryBtn {
                padding: 9px 16px;
                border-radius: 12px;
                border: 1px solid #0EA5E9;
                background: #0EA5E9;
                color: white;
                font-size: 12px;
                font-weight: 800;
            }
            QPushButton#PrimaryBtn:hover {
                background: #0284C7;
                border-color: #0284C7;
            }
            QPushButton#GhostBtn {
                padding: 9px 14px;
                border-radius: 12px;
                border: 1px solid #D9E2EC;
                background: #FFFFFF;
                color: #0F172A;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton#GhostBtn:hover {
                background: #F8FAFC;
            }
            QFrame#DetailPaginationBar {
                background: #F8FAFC;
                border: 1px solid #DDE7F2;
                border-radius: 18px;
            }
            QPushButton#PageNavButton {
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                border-radius: 21px;
                border: 1px solid #CBD5E1;
                background: #FFFFFF;
                color: #0F172A;
                font-size: 22px;
                font-weight: 950;
            }
            QPushButton#PageNavButton:hover {
                background: #EFF6FF;
                border-color: #93C5FD;
            }
            QPushButton#PageNavButton:disabled {
                background: #F1F5F9;
                color: #94A3B8;
                border-color: #E2E8F0;
            }
            QLabel#PageIndicator {
                color: #334155;
                font-size: 12px;
                font-weight: 900;
            }
            QScrollArea {
                border: 0px;
                background: transparent;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(18)

        hero = QFrame(self)
        hero.setObjectName("HeroPanel")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(12)
        title_wrap = QVBoxLayout()
        title_wrap.setContentsMargins(0, 0, 0, 0)
        title_wrap.setSpacing(7)
        self.title_label = QLabel("Sipariş Tahmini Kar Detayı")
        self.title_label.setObjectName("DialogTitle")
        self.subtitle_label = QLabel("Sipariş: -")
        self.subtitle_label.setObjectName("DialogSub")
        self.btn_export = QPushButton("Dışa Aktar")
        self.btn_export.setObjectName("GhostBtn")
        self.btn_export.clicked.connect(self._toggle_export_drawer)
        title_wrap.addWidget(self.title_label)
        title_wrap.addWidget(self.subtitle_label)
        hero_layout.addLayout(title_wrap, 1)
        hero_layout.addWidget(self.btn_export, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(hero)

        self.export_drawer = QFrame(self)
        self.export_drawer.setObjectName("ExportDrawer")
        export_layout = QHBoxLayout(self.export_drawer)
        export_layout.setContentsMargins(14, 12, 14, 12)
        export_layout.setSpacing(10)
        export_title = QLabel("Dışa aktarım")
        export_title.setObjectName("SectionTitle")
        export_hint = QLabel("Çıktı otomatik isimlendirilir; kaydetme yerini sen seçersin.")
        export_hint.setObjectName("DialogSub")
        export_hint.setWordWrap(True)
        export_excel = QPushButton("Excel olarak dışa aktar")
        export_excel.setObjectName("PrimaryBtn")
        export_excel.clicked.connect(self._export_to_excel)
        export_layout.addWidget(export_title, 0)
        export_layout.addWidget(export_hint, 1)
        export_layout.addWidget(export_excel, 0)
        self.export_drawer.setVisible(False)
        root.addWidget(self.export_drawer)

        body_row = QHBoxLayout()
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(14)

        self.content_scroll = QScrollArea(self)
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.content_scroll.viewport().setStyleSheet("background: transparent;")
        self.content_scroll.verticalScrollBar().valueChanged.connect(self._position_detail_overlays)
        content = QWidget(self.content_scroll)
        content.setStyleSheet("background: transparent;")
        self._content_widget = content
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 18, 0)
        content_layout.setSpacing(16)

        self.summary_card = QFrame(content)
        self.summary_card.setObjectName("EquationCard")
        summary_wrap = QVBoxLayout(self.summary_card)
        summary_wrap.setContentsMargins(0, 0, 0, 0)
        summary_wrap.setSpacing(14)
        summary_title = QLabel("Finans Özeti")
        summary_title.setObjectName("SectionTitle")
        summary_wrap.addWidget(summary_title)

        self.profit_panel = ClickableFrame(self.summary_card)
        self.profit_panel.setObjectName("ProfitHero")
        self.profit_panel.clicked.connect(self._toggle_summary_expanded)
        self.profit_panel.setMinimumHeight(170)
        profit_layout = QHBoxLayout(self.profit_panel)
        profit_layout.setContentsMargins(26, 24, 26, 22)
        profit_layout.setSpacing(20)
        self.profit_icon = ProfitMetricIcon("profit", "#15803D", "#DCFCE7", self.profit_panel)
        profit_layout.addWidget(self.profit_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        profit_text_layout = QVBoxLayout()
        profit_text_layout.setContentsMargins(0, 0, 0, 0)
        profit_text_layout.setSpacing(7)
        profit_label = QLabel("TAHMİNİ KAR")
        profit_label.setObjectName("EquationLabel")
        self.profit_value_label = QLabel("-")
        self.profit_value_label.setObjectName("ProfitValue")
        self.formula_label = QLabel("-")
        self.formula_label.setObjectName("FormulaText")
        self.profit_hint_label = QLabel("Satış ve maliyet denklemini açmak için tıkla")
        self.profit_hint_label.setObjectName("EquationHint")
        profit_text_layout.addWidget(profit_label)
        profit_text_layout.addWidget(self.profit_value_label)
        profit_text_layout.addWidget(self.formula_label)
        profit_text_layout.addWidget(self.profit_hint_label)
        profit_layout.addLayout(profit_text_layout, 1)
        self.profit_chevron_label = QLabel("v")
        self.profit_chevron_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.profit_chevron_label.setFixedSize(44, 44)
        self.profit_chevron_label.setStyleSheet(
            "border-radius: 22px; background: rgba(255,255,255,0.72); color: #475569; font-size: 24px; font-weight: 900;"
        )
        profit_layout.addWidget(self.profit_chevron_label, 0, Qt.AlignmentFlag.AlignVCenter)
        summary_wrap.addWidget(self.profit_panel)

        self.reveal_panel = SmoothHeightFrame(self.summary_card)
        self.reveal_panel.setObjectName("RevealPanel")
        self.reveal_panel.heightProgressChanged.connect(self._position_detail_overlays)
        self.reveal_panel.heightProgressChanged.connect(self._restore_detail_scroll_anchor)
        reveal_layout = QVBoxLayout(self.reveal_panel)
        reveal_layout.setContentsMargins(0, 0, 0, 0)
        reveal_layout.setSpacing(0)
        equation_row = QHBoxLayout()
        equation_row.setContentsMargins(0, 0, 0, 0)
        equation_row.setSpacing(14)
        self.sale_metric = self._create_equation_metric(
            "sale",
            "TOPLAM SATIŞ",
            accent="#16A34A",
            tab_key="sale",
        )
        self.cost_metric = self._create_equation_metric(
            "cost",
            "TOPLAM MALİYET",
            accent="#DC2626",
            tab_key="cost",
        )
        operator_badge = QFrame(self.summary_card)
        operator_badge.setObjectName("OperatorBadge")
        operator_badge.setFixedSize(48, 48)
        operator_layout = QVBoxLayout(operator_badge)
        operator_layout.setContentsMargins(0, 0, 0, 2)
        operator_label = QLabel("-")
        operator_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        operator_label.setStyleSheet("font-size: 34px; font-weight: 900; color: #475569;")
        operator_layout.addWidget(operator_label)
        operator_host = QWidget(self.summary_card)
        operator_host.setFixedWidth(64)
        operator_host_layout = QVBoxLayout(operator_host)
        operator_host_layout.setContentsMargins(8, 47, 8, 0)
        operator_host_layout.setSpacing(0)
        operator_host_layout.addWidget(operator_badge, 0, Qt.AlignmentFlag.AlignHCenter)
        operator_host_layout.addStretch(1)
        equation_row.addWidget(self.sale_metric, 1, Qt.AlignmentFlag.AlignTop)
        equation_row.addWidget(operator_host, 0)
        equation_row.addWidget(self.cost_metric, 1, Qt.AlignmentFlag.AlignTop)
        reveal_layout.addLayout(equation_row)
        summary_wrap.addWidget(self.reveal_panel)
        content_layout.addWidget(self.summary_card)
        self.detail_drawer_spacer = QWidget(content)
        self.detail_drawer_spacer.setStyleSheet("background: transparent;")
        self.detail_drawer_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.detail_drawer_spacer.setFixedHeight(0)
        self.detail_drawer_spacer.setVisible(False)
        content_layout.addWidget(self.detail_drawer_spacer)
        self.lines_layout = QVBoxLayout()

        self.missing_panel = ClickableFrame(content)
        self.missing_panel.setObjectName("MissingPanel")
        self.missing_panel.clicked.connect(self._toggle_missing_expanded)
        self.missing_panel.setStyleSheet(
            """
            QFrame#MissingPanel {
                background: #FFFBEB;
                border: 3px solid #F59E0B;
                border-radius: 22px;
            }
            QFrame#MissingPanel:hover {
                background: #FFF7ED;
                border-color: #B45309;
            }
            """
        )
        missing_layout = QVBoxLayout(self.missing_panel)
        missing_layout.setContentsMargins(22, 18, 22, 18)
        missing_layout.setSpacing(14)

        missing_header = QHBoxLayout()
        missing_header.setContentsMargins(0, 0, 0, 0)
        missing_header.setSpacing(18)
        missing_icon = QLabel("!")
        missing_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        missing_icon.setFixedSize(64, 64)
        missing_icon.setStyleSheet(
            "background: #FEF3C7; border: 2px solid #F59E0B; border-radius: 32px; "
            "color: #B45309; font-size: 28px; font-weight: 950;"
        )
        missing_text = QVBoxLayout()
        missing_text.setContentsMargins(0, 0, 0, 0)
        missing_text.setSpacing(7)
        self.missing_title = QLabel("EKSİK / BEKLEYEN VERİLER")
        self.missing_title.setObjectName("EquationLabel")
        self.missing_value_label = QLabel("0")
        self.missing_value_label.setObjectName("MissingValue")
        self.missing_hint_label = QLabel("Eksik kayıt detaylarını görmek için tıkla")
        self.missing_hint_label.setObjectName("MissingHint")
        self.missing_hint_label.setWordWrap(True)
        missing_text.addWidget(self.missing_title)
        missing_text.addWidget(self.missing_value_label)
        missing_text.addWidget(self.missing_hint_label)
        self.missing_chevron_label = QLabel("v")
        self.missing_chevron_label.setObjectName("MissingChevron")
        self.missing_chevron_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.missing_chevron_label.setFixedSize(44, 44)
        missing_header.addWidget(missing_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        missing_header.addLayout(missing_text, 1)
        missing_header.addWidget(self.missing_chevron_label, 0, Qt.AlignmentFlag.AlignVCenter)
        missing_layout.addLayout(missing_header)

        self.missing_body_layout = QVBoxLayout()
        self.missing_body_layout.setContentsMargins(0, 0, 0, 0)
        self.missing_body_layout.setSpacing(8)
        missing_layout.addLayout(self.missing_body_layout)
        content_layout.addWidget(self.missing_panel)
        content_layout.addStretch(1)
        self.content_scroll.setWidget(content)
        body_row.addWidget(self.content_scroll, 1)

        side_host = QWidget(self)
        side_host.setFixedWidth(310)
        side_layout = QVBoxLayout(side_host)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)

        self.health_card, self.health_body_layout = self._create_side_card(side_host, "Veri Sağlığı")
        self.logic_card, self.logic_body_layout = self._create_side_card(side_host, "Hesap Mantığı")
        side_layout.addWidget(self.health_card)
        side_layout.addWidget(self.logic_card)
        side_layout.addStretch(1)
        body_row.addWidget(side_host, 0)
        root.addLayout(body_row, 1)

        footer = QFrame(self)
        footer.setObjectName("FooterCard")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 12, 16, 12)
        footer_layout.setSpacing(12)
        self.footer_hint = QLabel(
            "Hesap, sipariş satırları ile ilandaki stok ve maliyet eşleşmelerinden üretilir."
        )
        self.footer_hint.setObjectName("DialogSub")
        self.footer_hint.setWordWrap(True)
        self.btn_close = QPushButton("Kapat")
        self.btn_close.setObjectName("PrimaryBtn")
        self.btn_close.clicked.connect(self.close)
        footer_layout.addWidget(self.footer_hint, 1)
        footer_layout.addWidget(self.btn_close, 0)
        root.addWidget(footer)

    @staticmethod
    def _clear_layout(layout: QVBoxLayout | QHBoxLayout | QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            if child_layout is not None:
                OrderProfitBreakdownWindow._clear_layout(child_layout)
                child_layout.deleteLater()
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _create_equation_metric(self, key: str, title: str, *, accent: str, tab_key: str) -> ClickableFrame:
        button = ClickableFrame(self.summary_card)
        button.setObjectName("EquationMetric")
        button.setMinimumWidth(0)
        button.setMinimumHeight(142)
        button.setProperty("accent", accent)
        button.clicked.connect(lambda: self._toggle_detail_tab(tab_key))
        layout = QVBoxLayout(button)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(0)

        head_host = QWidget(button)
        head_host.setFixedHeight(72)
        head = QHBoxLayout(head_host)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(16)

        icon = ProfitMetricIcon(
            "sale" if key == "sale" else "cost",
            accent,
            "#EAF8EF" if key == "sale" else "#FFF1F2",
            button,
        )
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("EquationLabel")
        value_label = QLabel("-")
        value_label.setObjectName("EquationValue")
        hint_label = QLabel("Detayı görmek için tıkla  ->")
        hint_label.setObjectName("EquationHint")
        text_layout.addWidget(title_label)
        text_layout.addWidget(value_label)
        text_layout.addWidget(hint_label)
        head.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addLayout(text_layout, 1)
        chevron = QLabel(">")
        chevron.setText(">")
        chevron.setStyleSheet("font-size: 28px; font-weight: 900; color: #64748B;")
        head.addWidget(chevron, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(head_host)

        drawer = SmoothHeightFrame(self.content_scroll.viewport(), duration_ms=467)
        drawer.setObjectName("InnerDrawer")
        drawer.setProperty("kind", key)
        drawer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        drawer.heightProgressChanged.connect(self._position_detail_overlays)
        drawer.heightProgressChanged.connect(self._sync_detail_drawer_spacer)
        drawer.heightProgressChanged.connect(self._restore_detail_scroll_anchor)
        drawer_layout = QVBoxLayout(drawer)
        drawer_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        drawer_layout.setContentsMargins(14, 12, 14, 12)
        drawer_layout.setSpacing(8)
        layout.addStretch(1)

        self._summary_cards[key] = {
            "button": button,
            "icon": icon,
            "title": title_label,
            "value": value_label,
            "note": hint_label,
            "chevron": chevron,
            "header": head_host,
            "drawer": drawer,
            "drawer_layout": drawer_layout,
        }
        self._style_equation_metric(key, active=False)
        return button

    def _style_equation_metric(self, key: str, *, active: bool) -> None:
        card = self._summary_cards.get(key) or {}
        button = card.get("button")
        value_label = card.get("value")
        chevron = card.get("chevron")
        if not isinstance(button, QFrame):
            return
        accent = str(button.property("accent") or "#0F172A")
        border = accent
        bg = "#F0FDF4" if key == "sale" else "#FFF1F2"
        if not active:
            bg = "#FFFFFF"
        button.setStyleSheet(
            "QFrame#EquationMetric {"
            f"border-radius: 24px; background: {bg};"
            f"border: 2px solid {border}; color: #0F172A;"
            "}"
        )
        if isinstance(value_label, QLabel):
            value_label.setStyleSheet(f"font-size: 34px; font-weight: 950; color: {accent};")
        if isinstance(chevron, QLabel):
            chevron.setText("v" if active else ">")

    def _sync_equation_metric_height(self, key: str) -> None:
        card = self._summary_cards.get(key) or {}
        button = card.get("button")
        drawer = card.get("drawer")
        header = card.get("header")
        if not isinstance(button, QWidget) or not isinstance(drawer, SmoothHeightFrame):
            return
        target = 142
        if not drawer.isHidden() or drawer.isExpanded() or drawer.isAnimating():
            layout = button.layout()
            header_height = int(header.height()) if isinstance(header, QWidget) else 72
            if layout is not None:
                margins = layout.contentsMargins()
                target = max(target, int(margins.top() + margins.bottom() + header_height + drawer.maximumHeight() + 8))
        button.setMinimumHeight(target)
        button.updateGeometry()

    def _create_summary_card(self, key: str, title: str) -> QFrame:
        card = QFrame(self)
        card.setObjectName("SummaryCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        value_label = QLabel("-")
        value_label.setObjectName("CardValue")
        note_label = QLabel("")
        note_label.setObjectName("CardNote")
        note_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(note_label)
        self._summary_cards[key] = {
            "title": title_label,
            "value": value_label,
            "note": note_label,
        }
        return card

    def _create_side_card(self, parent: QWidget, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(parent)
        card.setObjectName("SideCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        layout.addWidget(title_label)
        layout.addLayout(body)
        return card, body

    def _build_badge(self, text: str, *, tone: str) -> QLabel:
        palette = {
            "ok": ("#E8FFF3", "#BBF7D0", "#15803D"),
            "warn": ("#FFF7E8", "#FCD34D", "#B45309"),
            "danger": ("#FEF2F2", "#FECACA", "#B91C1C"),
            "info": ("#EFF6FF", "#BFDBFE", "#1D4ED8"),
            "muted": ("#F8FAFC", "#E2E8F0", "#475569"),
        }
        bg, border, text_color = palette.get(tone, palette["muted"])
        label = QLabel(text)
        label.setStyleSheet(
            f"padding: 6px 10px; border-radius: 11px; border: 1px solid {border}; background: {bg}; color: {text_color}; font-size: 11px; font-weight: 700;"
        )
        return label

    def _build_chip(self, label: str, value: str, *, tone: str = "neutral") -> QLabel:
        palette = {
            "neutral": ("#FFFFFF", "#D9E2EC", "#0F172A"),
            "info": ("#EFF6FF", "#BFDBFE", "#1D4ED8"),
            "ok": ("#ECFDF5", "#A7F3D0", "#047857"),
            "warn": ("#FFF7ED", "#FED7AA", "#C2410C"),
            "danger": ("#FEF2F2", "#FECACA", "#B91C1C"),
            "muted": ("#F8FAFC", "#E2E8F0", "#64748B"),
        }
        bg, border, color = palette.get(tone, palette["neutral"])
        chip = QLabel(f"{label}  {value}")
        chip.setStyleSheet(
            f"padding: 6px 10px; border-radius: 11px; border: 1px solid {border}; background: {bg}; color: {color}; font-size: 11px; font-weight: 700;"
        )
        return chip

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            return float(value)
        except Exception:
            return None

    def _set_summary_card(self, key: str, *, value: str, note: str, tone: str = "neutral") -> None:
        card = self._summary_cards.get(key) or {}
        value_label = card.get("value")
        note_label = card.get("note")
        if value_label is not None:
            color_map = {
                "neutral": "#0F172A",
                "ok": "#15803D",
                "danger": "#B91C1C",
                "muted": "#94A3B8",
                "warn": "#B45309",
            }
            value_label.setText(value)
            value_label.setStyleSheet(
                f"font-size: 28px; font-weight: 900; color: {color_map.get(tone, '#0F172A')};"
            )
        if note_label is not None:
            note_label.setText(note)

    def _build_side_stat_row(self, label: str, value: str, *, tone: str = "neutral") -> QFrame:
        row = QFrame(self)
        row.setObjectName("SideStatRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(12)

        color_map = {
            "neutral": "#475569",
            "ok": "#15803D",
            "danger": "#B91C1C",
            "warn": "#B45309",
            "muted": "#64748B",
        }
        fill_map = {
            "neutral": "#EEF2F7",
            "ok": "#DCFCE7",
            "danger": "#FEE2E2",
            "warn": "#FEF3C7",
            "muted": "#F1F5F9",
        }
        accent = color_map.get(tone, "#475569")
        fill = fill_map.get(tone, "#EEF2F7")

        dot = QLabel("")
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background: {accent}; border-radius: 5px;")

        lbl = QLabel(label)
        lbl.setObjectName("SideStatLabel")

        val = QLabel(value)
        val.setObjectName("SideValue")
        val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val.setMinimumWidth(46)
        val.setStyleSheet(
            f"padding: 5px 10px; border-radius: 11px; background: {fill}; "
            f"color: {accent}; font-size: 13px; font-weight: 900;"
        )

        layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl, 1)
        layout.addWidget(val, 0)
        return row

    def _build_missing_reason_row(self, text: str) -> QFrame:
        row = QFrame(self.missing_panel)
        row.setObjectName("MissingReasonRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(10)

        icon = QLabel("!")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(26, 26)
        icon.setStyleSheet(
            "background: #FEF3C7; border: 1px solid #FBBF24; border-radius: 13px; "
            "color: #B45309; font-size: 14px; font-weight: 950;"
        )

        row_label = QLabel(text)
        row_label.setObjectName("MissingReasonText")
        row_label.setWordWrap(True)

        row_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        row_layout.addWidget(row_label, 1)
        return row

    def _detail_page_count(self, total_rows: int) -> int:
        per_page = max(1, int(self._DETAIL_ROWS_PER_PAGE))
        return max(1, (max(0, int(total_rows)) + per_page - 1) // per_page)

    def _detail_page_bounds(self, key: str, total_rows: int) -> tuple[int, int, int, int]:
        normalized = "sale" if key == "sale" else "cost"
        per_page = max(1, int(self._DETAIL_ROWS_PER_PAGE))
        page_count = self._detail_page_count(total_rows)
        current = max(0, min(int(self._detail_page_indexes.get(normalized, 0)), page_count - 1))
        self._detail_page_indexes[normalized] = current
        start = current * per_page
        end = start + per_page
        return current, page_count, start, end

    def _change_detail_page(self, key: str, delta: int) -> None:
        normalized = "sale" if key == "sale" else "cost"
        current = max(0, int(self._detail_page_indexes.get(normalized, 0)))
        self._detail_page_indexes[normalized] = current + int(delta or 0)
        self._populate_detail_drawer(normalized)
        self._render_detail_drawer()

    def _build_detail_pagination_bar(self, key: str, total_rows: int) -> QFrame:
        current, page_count, _start, _end = self._detail_page_bounds(key, total_rows)
        bar = QFrame(self)
        bar.setObjectName("DetailPaginationBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        prev_btn = QPushButton("<")
        prev_btn.setObjectName("PageNavButton")
        prev_btn.setEnabled(current > 0)
        prev_btn.clicked.connect(lambda _checked=False, k=key: self._change_detail_page(k, -1))

        page_label = QLabel(f"Sayfa {current + 1} / {page_count}")
        page_label.setObjectName("PageIndicator")
        page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        next_btn = QPushButton(">")
        next_btn.setObjectName("PageNavButton")
        next_btn.setEnabled(current < page_count - 1)
        next_btn.clicked.connect(lambda _checked=False, k=key: self._change_detail_page(k, 1))

        layout.addWidget(prev_btn, 0)
        layout.addStretch(1)
        layout.addWidget(page_label, 0)
        layout.addStretch(1)
        layout.addWidget(next_btn, 0)
        return bar

    def _build_logic_note(self, text: str) -> QLabel:
        lbl = QLabel(f"- {text}")
        lbl.setObjectName("SideNote")
        lbl.setWordWrap(True)
        return lbl

    @staticmethod
    def _safe_export_filename(label: str, suffix: str) -> str:
        raw = f"{label}_{suffix}".strip() or "tahmini_kar_detayi"
        cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_")[:120] or "tahmini_kar_detayi"

    def _toggle_export_drawer(self) -> None:
        self._export_drawer_visible = not self._export_drawer_visible
        self.export_drawer.setVisible(self._export_drawer_visible)

    def _export_to_excel(self) -> None:
        order_number = _safe_str(getattr(self._order, "orderNumber", "")) or "-"
        default_name = self._safe_export_filename(
            order_number,
            f"tahmini_kar_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Excel olarak dışa aktar",
            str(Path.home() / "Desktop" / default_name),
            "Excel Dosyası (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path = f"{path}.xlsx"
        result = write_order_profit_payload_to_excel(
            order_number=order_number,
            estimated_profit_payload=dict(self._payload or {}),
            output_path=path,
        )
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        self.btn_export.setText("Excel hazır")
        self.export_drawer.setVisible(False)
        self._export_drawer_visible = False
        QTimer.singleShot(1400, lambda: self.btn_export.setText("Dışa Aktar"))
    def _toggle_summary_expanded(self) -> None:
        self._capture_detail_scroll_anchor()
        self._summary_expanded = not self._summary_expanded
        if not self._summary_expanded:
            self._active_detail_tabs.clear()
        self._render_detail_drawer(animated=False)

    def _toggle_detail_tab(self, tab_key: str) -> None:
        self._capture_detail_scroll_anchor()
        normalized = "sale" if tab_key == "sale" else "cost"
        if not self._summary_expanded:
            self._summary_expanded = True
        if normalized in self._active_detail_tabs:
            self._active_detail_tabs.remove(normalized)
        else:
            self._active_detail_tabs.add(normalized)
        self._render_detail_drawer(animated=True)

    def _capture_detail_scroll_anchor(self) -> None:
        scroll = getattr(self, "content_scroll", None)
        if not isinstance(scroll, QScrollArea):
            self._detail_scroll_value = None
            return
        self._detail_scroll_value = int(scroll.verticalScrollBar().value())
        content = getattr(self, "_content_widget", None)
        if isinstance(content, QWidget) and content.width() > 0:
            locked_width = int(content.width())
            content.setMinimumWidth(locked_width)
            content.setMaximumWidth(locked_width)
            self._detail_viewport_lock_generation += 1
            generation = self._detail_viewport_lock_generation
            QTimer.singleShot(1400, lambda: self._release_detail_viewport_lock(generation))

    def _restore_detail_scroll_anchor(self) -> None:
        scroll_value = getattr(self, "_detail_scroll_value", None)
        scroll = getattr(self, "content_scroll", None)
        if scroll_value is None or not isinstance(scroll, QScrollArea):
            return
        bar = scroll.verticalScrollBar()
        if bar.value() != scroll_value:
            bar.setValue(scroll_value)

    def _position_detail_overlays(self) -> None:
        scroll = getattr(self, "content_scroll", None)
        if not isinstance(scroll, QScrollArea):
            return
        viewport = scroll.viewport()
        for meta in self._summary_cards.values():
            if not isinstance(meta, dict):
                continue
            button = meta.get("button")
            drawer = meta.get("drawer")
            if not isinstance(button, QWidget) or not isinstance(drawer, SmoothHeightFrame):
                continue
            height = max(0, int(drawer.maximumHeight()))
            if height <= 0 and not drawer.isAnimating() and not drawer.isExpanded():
                drawer.setGeometry(0, 0, 0, 0)
                continue
            top_left = button.mapTo(viewport, QPoint(0, button.height() + 8))
            width = max(0, int(button.width()))
            drawer.setGeometry(top_left.x(), top_left.y(), width, height)
            drawer.raise_()

    def _active_detail_drawer_height(self) -> int:
        height = 0
        for key in ("sale", "cost"):
            drawer = self._summary_cards.get(key, {}).get("drawer")
            if not isinstance(drawer, SmoothHeightFrame):
                continue
            if self._summary_expanded and key in self._active_detail_tabs:
                height = max(height, int(drawer.expandedHeight()), int(drawer.maximumHeight()))
                continue
            if drawer.isHidden() and not drawer.isExpanded() and not drawer.isAnimating():
                continue
            if drawer.isAnimating():
                height = max(height, int(drawer.expandedHeight()), int(drawer.maximumHeight()))
                continue
            height = max(height, int(drawer.maximumHeight()))
        return max(0, height)

    def _sync_detail_drawer_spacer(self) -> None:
        spacer = getattr(self, "detail_drawer_spacer", None)
        if not isinstance(spacer, QWidget):
            return
        height = self._active_detail_drawer_height()
        target = height + 24 if height > 0 else 0
        if spacer.maximumHeight() != target:
            spacer.setVisible(target > 0)
            spacer.setMinimumHeight(target)
            spacer.setMaximumHeight(target)
            spacer.updateGeometry()
            content = getattr(self, "_content_widget", None)
            if isinstance(content, QWidget):
                layout = content.layout()
                if layout is not None:
                    layout.activate()
                content.updateGeometry()
                scroll = getattr(self, "content_scroll", None)
                if isinstance(scroll, QScrollArea):
                    target_width = max(1, int(scroll.viewport().width()))
                    target_height = max(int(content.height()), int(content.sizeHint().height()))
                    content.resize(target_width, target_height)

    def _release_detail_viewport_lock(self, generation: int) -> None:
        if generation != self._detail_viewport_lock_generation:
            return
        content = getattr(self, "_content_widget", None)
        try:
            if isinstance(content, QWidget):
                content.setMinimumWidth(0)
                content.setMaximumWidth(16777215)
                content.updateGeometry()
        except RuntimeError:
            return

    def _sync_reveal_panel_height(self, *, animated: bool = False) -> None:
        reveal = getattr(self, "reveal_panel", None)
        if not self._summary_expanded or not isinstance(reveal, SmoothHeightFrame) or reveal.isAnimating():
            return
        layout = reveal.layout()
        if layout is None:
            return
        margins = layout.contentsMargins()
        target = int(margins.top() + margins.bottom())
        row_height = 0
        for index in range(layout.count()):
            item = layout.itemAt(index)
            child_layout = item.layout() if item is not None else None
            if child_layout is None:
                widget = item.widget() if item is not None else None
                if isinstance(widget, QWidget):
                    target += self._effective_layout_height(widget)
                continue
            row_height = max(row_height, self._effective_layout_height(child_layout))
        minimum_row_height = 0
        for card in self._summary_cards.values():
            button = card.get("button") if isinstance(card, dict) else None
            if isinstance(button, QWidget):
                minimum_row_height = max(minimum_row_height, int(button.minimumHeight()))
        target += max(row_height, minimum_row_height)
        target = max(1, target)
        if int(reveal.maximumHeight()) == target:
            return
        if animated:
            reveal.refreshExpandedHeight(animated=True)
            return
        reveal.setMaximumHeight(target)
        reveal.updateGeometry()

    def _effective_layout_height(self, target: QWidget | QVBoxLayout | QHBoxLayout) -> int:
        if isinstance(target, SmoothHeightFrame):
            if target.isHidden() and not target.isExpanded() and not target.isAnimating():
                return 0
            return max(0, int(target.maximumHeight()))
        if isinstance(target, QWidget):
            layout = target.layout()
            if isinstance(layout, (QVBoxLayout, QHBoxLayout)):
                return self._effective_layout_height(layout)
            hint_height = int(target.sizeHint().height())
            if hint_height > 0:
                return hint_height
            min_height = int(target.minimumHeight())
            max_height = int(target.maximumHeight())
            if min_height > 0 and max_height < 16777215:
                return min(min_height, max_height)
            if min_height > 0:
                return min_height
            if max_height > 0 and max_height < 16777215:
                return max_height
            return max(0, int(target.height()))
        if isinstance(target, QHBoxLayout):
            margins = target.contentsMargins()
            height = int(margins.top() + margins.bottom())
            child_height = 0
            for index in range(target.count()):
                item = target.itemAt(index)
                widget = item.widget() if item is not None else None
                child_layout = item.layout() if item is not None else None
                if isinstance(widget, QWidget):
                    child_height = max(child_height, self._effective_layout_height(widget))
                elif isinstance(child_layout, (QVBoxLayout, QHBoxLayout)):
                    child_height = max(child_height, self._effective_layout_height(child_layout))
            return height + child_height
        margins = target.contentsMargins()
        height = int(margins.top() + margins.bottom())
        spacing = max(0, int(target.spacing()))
        measured = 0
        for index in range(target.count()):
            item = target.itemAt(index)
            widget = item.widget() if item is not None else None
            child_layout = item.layout() if item is not None else None
            child_height = 0
            if isinstance(widget, QWidget):
                child_height = self._effective_layout_height(widget)
            elif isinstance(child_layout, (QVBoxLayout, QHBoxLayout)):
                child_height = self._effective_layout_height(child_layout)
            if child_height <= 0:
                continue
            if measured:
                height += spacing
            height += child_height
            measured += 1
        return height

    def _set_active_detail_tab(self, tab_key: str) -> None:
        self._summary_expanded = True
        self._active_detail_tabs.add("sale" if tab_key == "sale" else "cost")
        self._render_detail_drawer()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_detail_overlays()

    def _set_tab_button_state(self, button: QPushButton, *, active: bool) -> None:
        button.setProperty("active", "true" if active else "false")
        button.style().unpolish(button)
        button.style().polish(button)

    def _detail_row(
        self,
        label: str,
        value: str,
        *,
        note: str = "",
        tone: str = "neutral",
        summary: bool = False,
        meta: tuple[str, str] | None = None,
    ) -> QFrame:
        row = QFrame(self)
        row.setObjectName("LedgerTotalRow" if summary else "LedgerRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14 if summary else 12, 12 if summary else 10, 14 if summary else 12, 12 if summary else 10)
        layout.setSpacing(12)
        color_map = {
            "neutral": "#0F172A",
            "ok": "#15803D",
            "danger": "#B91C1C",
            "warn": "#B45309",
        }
        fill_map = {
            "neutral": "#E2E8F0",
            "ok": "#BBF7D0",
            "danger": "#FECACA",
            "warn": "#FED7AA",
        }
        accent = color_map.get(tone, "#0F172A")
        if not summary:
            marker = QLabel("")
            marker.setObjectName("LedgerMarker")
            marker.setFixedSize(14, 14)
            marker.setStyleSheet(f"background: {fill_map.get(tone, '#E2E8F0')}; border: 2px solid {accent};")
            layout.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)
        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(5)
        lbl = QLabel(label)
        lbl.setObjectName("RowTitle")
        lbl.setWordWrap(True)
        if summary:
            lbl.setStyleSheet("font-size: 14px; font-weight: 950; color: #0F172A;")
        text_wrap.addWidget(lbl)
        if note:
            note_label = QLabel(note)
            note_label.setObjectName("RowNote")
            note_label.setWordWrap(True)
            text_wrap.addWidget(note_label)
        if meta:
            meta_row = QHBoxLayout()
            meta_row.setContentsMargins(0, 2, 0, 0)
            meta_row.setSpacing(6)
            for label_text, value_text in (("Adet", meta[0]), ("Birim", meta[1])):
                chip = QLabel(f"{label_text} {value_text}")
                chip.setStyleSheet(
                    "padding: 4px 8px; border-radius: 9px; border: 1px solid #DDE7F2; "
                    "background: #F8FAFC; color: #475569; font-size: 10px; font-weight: 800;"
                )
                meta_row.addWidget(chip, 0)
            meta_row.addStretch(1)
            text_wrap.addLayout(meta_row)
        val = QLabel(value)
        val.setObjectName("DetailValue")
        val.setStyleSheet(
            f"font-size: {'16px' if summary else '13px'}; "
            f"font-weight: {'950' if summary else '900'}; "
            f"color: {accent};"
        )
        layout.addLayout(text_wrap, 1)
        layout.addWidget(val, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _populate_detail_drawers(self) -> None:
        self._populate_detail_drawer("sale")
        self._populate_detail_drawer("cost")

    def _populate_detail_drawer(self, key: str) -> None:
        normalized = "sale" if key == "sale" else "cost"
        drawer = self._summary_cards.get(normalized, {}).get("drawer")
        drawer_layout = self._summary_cards.get(normalized, {}).get("drawer_layout")
        if not isinstance(drawer_layout, QVBoxLayout):
            return
        detail = dict(self._payload.get("estimated_profit_detail") or {})
        lines = list(detail.get("lines") or [])
        results = dict(detail.get("results") or {})
        self._clear_layout(drawer_layout)

        if normalized == "sale":
            total_sale = 0.0
            for line in lines:
                amount = self._optional_float(line.get("amount")) or 0.0
                total_sale += amount
            _current, page_count, start, end = self._detail_page_bounds("sale", len(lines))
            for line in lines[start:end]:
                amount = self._optional_float(line.get("amount")) or 0.0
                qty = _safe_str(line.get("qty_text")) or "-"
                unit = _safe_str(line.get("unit_price_text")) or "-"
                drawer_layout.addWidget(
                    self._detail_row(
                        _safe_str(line.get("title")) or "Ürün",
                        _safe_str(line.get("amount_text")) or _amount_text(amount),
                        note=_safe_str(line.get("listing_title")) or "Sipariş satırı",
                        tone="ok",
                        meta=(qty, unit),
                    )
                )
            if not lines:
                drawer_layout.addWidget(self._detail_row("Sipariş satırı bulunamadı", "-", tone="warn"))
            elif page_count > 1:
                drawer_layout.addWidget(self._build_detail_pagination_bar("sale", len(lines)))
            drawer_layout.addWidget(
                self._detail_row(
                    "Toplam Satış",
                    _amount_text(total_sale),
                    note="OrderItem satırlarından toplandı.",
                    tone="ok",
                    summary=True,
                )
            )
        else:
            applied_costs = [row for row in list(detail.get("applied_costs") or []) if isinstance(row, dict)]
            if not applied_costs:
                for line in lines:
                    line_detail = dict(line.get("detail") or {})
                    for cost in list(line_detail.get("applied_costs") or []):
                        if isinstance(cost, dict):
                            applied_costs.append(dict(cost))
            if not applied_costs:
                total_cost = self._optional_float(results.get("total_costs")) or 0.0
                if total_cost > 0:
                    applied_costs = [{"label": "Toplam maliyet", "gross": total_cost, "kind": "other"}]
                else:
                    drawer_layout.addWidget(self._detail_row("Maliyet kaydı bulunamadı", "-", tone="warn"))
            _current, page_count, start, end = self._detail_page_bounds("cost", len(applied_costs))
            for cost in applied_costs[start:end]:
                label = _safe_str(cost.get("label")) or _safe_str(cost.get("key")) or "Maliyet"
                label_key = label.strip().casefold()
                if "stock" in label_key or "stok" in label_key:
                    note_text = "Eşleşen stok kartı maliyeti"
                    label = "Stok Maliyeti"
                elif "komisyon" in label_key or "commission" in label_key:
                    note_text = _safe_str(cost.get("note")) or "Platform komisyonu"
                    label = "Komisyon bedeli"
                elif "kargo" in label_key or "cargo" in label_key:
                    note_text = _safe_str(cost.get("note")) or "Tahmini gönderim maliyeti"
                    label = "Kargo"
                else:
                    note_text = _safe_str(cost.get("note")) or "Tanımlı maliyet kalemi"
                amount = self._optional_float(cost.get("gross"))
                if amount is None:
                    amount = self._optional_float(cost.get("value"))
                if amount is None:
                    continue
                drawer_layout.addWidget(self._detail_row(label, _amount_text(amount), note=note_text, tone="danger"))
            if page_count > 1:
                drawer_layout.addWidget(self._build_detail_pagination_bar("cost", len(applied_costs)))
            drawer_layout.addWidget(
                self._detail_row(
                    "Maliyet Toplamı",
                    _safe_str(results.get("total_costs_text")) or _amount_text(self._optional_float(results.get("total_costs"))),
                    note="Stok ve tanımlı maliyet kalemlerinden toplandı.",
                    tone="danger",
                    summary=True,
                )
            )

        if isinstance(drawer, SmoothHeightFrame) and drawer.isExpanded():
            drawer.refreshExpandedHeight(animated=False)
        self._sync_detail_drawer_spacer()
        self._position_detail_overlays()

    def _render_detail_drawer(self, *, animated: bool = False) -> None:
        if not hasattr(self, "reveal_panel"):
            return
        if isinstance(self.reveal_panel, SmoothHeightFrame):
            target_summary_open = bool(self._summary_expanded)
            if self.reveal_panel.isExpanded() != target_summary_open:
                self.reveal_panel.setExpanded(target_summary_open, animated=animated)
        else:
            self.reveal_panel.setVisible(bool(self._summary_expanded))
        if hasattr(self, "profit_chevron_label"):
            self.profit_chevron_label.setText("^" if self._summary_expanded else "v")
        if hasattr(self, "profit_hint_label"):
            self.profit_hint_label.setText(
                "Satış ve maliyet denklemini kapatmak için tıkla"
                if self._summary_expanded
                else "Satış ve maliyet denklemini açmak için tıkla"
            )

        self._sync_detail_drawer_spacer()
        for key in ("sale", "cost"):
            active = self._summary_expanded and key in self._active_detail_tabs
            self._style_equation_metric(key, active=active)
            drawer = self._summary_cards.get(key, {}).get("drawer")
            if not active:
                if isinstance(drawer, SmoothHeightFrame):
                    drawer.setExpanded(False, animated=animated)
                elif isinstance(drawer, QFrame):
                    drawer.setVisible(False)
                continue
            if isinstance(drawer, SmoothHeightFrame):
                drawer.setExpanded(True, animated=animated)
            elif isinstance(drawer, QFrame):
                drawer.setVisible(True)
        self._sync_detail_drawer_spacer()
        self._position_detail_overlays()

    def _build_line_breakdown(self, line: dict[str, Any]) -> QWidget:
        wrap = QWidget(self)
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        detail = dict(line.get("detail") or {})
        results = dict(detail.get("results") or {})
        sale_value = self._optional_float(line.get("amount")) or 0.0
        payout_value = self._optional_float(results.get("payout_total")) or 0.0
        marketplace_deduction = max(0.0, sale_value - payout_value)
        cost_value = self._optional_float(results.get("total_costs")) or 0.0
        profit_value = self._optional_float(line.get("estimated_profit")) or 0.0
        base_value = max(sale_value, marketplace_deduction, cost_value, abs(profit_value), 1.0)

        track = QFrame(wrap)
        track.setObjectName("BreakdownTrack")
        track.setFixedHeight(12)
        track_layout = QHBoxLayout(track)
        track_layout.setContentsMargins(4, 2, 4, 2)
        track_layout.setSpacing(4)

        segments = []
        if marketplace_deduction > 0:
            segments.append((marketplace_deduction, "#0EA5E9"))
        if cost_value > 0:
            segments.append((cost_value, "#F59E0B"))
        if profit_value > 0:
            segments.append((profit_value, "#10B981"))
        elif profit_value < 0:
            segments.append((abs(profit_value), "#EF4444"))
        if not segments and sale_value > 0:
            segments.append((sale_value, "#CBD5E1"))

        for value, color in segments:
            segment = QFrame(track)
            segment.setStyleSheet(f"background: {color}; border-radius: 4px;")
            track_layout.addWidget(segment, max(1, int(round((value / base_value) * 100))))

        note = QLabel(
            "Gelir: "
            f"{_amount_text(sale_value)}  -  Tahsilat: {_amount_text(payout_value)}  -  Masraf: {_amount_text(cost_value)}"
        )
        note.setObjectName("RowNote")
        note.setText(
            "Gelir: "
            f"{_amount_text(sale_value)}  |  Pazaryeri kesintisi: {_amount_text(marketplace_deduction)}  |  Masraf: {_amount_text(cost_value)}"
        )
        note.setWordWrap(True)
        layout.addWidget(track)
        layout.addWidget(note)
        return wrap

    def _build_line_card(self, line: dict[str, Any]) -> QFrame:
        card = QFrame(self)
        card.setObjectName("LineCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel(_safe_str(line.get("title")) or "Ürün")
        title.setObjectName("RowTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        listing_title = _safe_str(line.get("listing_title"))
        match_text = (
            f"İlan: {listing_title}"
            if listing_title
            else "İlan eşleşmesi yok. Tahmini kâr bu satırda bloke."
        )
        listing_note = QLabel(match_text)
        listing_note.setObjectName("RowNote")
        listing_note.setWordWrap(True)
        layout.addWidget(listing_note)

        chips_row = QHBoxLayout()
        chips_row.setContentsMargins(0, 0, 0, 0)
        chips_row.setSpacing(8)
        chips_row.addWidget(self._build_chip("Birim", _safe_str(line.get("unit_price_text")) or "-", tone="info"))
        chips_row.addWidget(self._build_chip("Adet", _safe_str(line.get("qty_text")) or "-", tone="neutral"))
        chips_row.addWidget(self._build_chip("Satış", _safe_str(line.get("amount_text")) or "-", tone="ok"))
        profit_tone = "muted"
        if bool(line.get("estimated_profit_ready")):
            try:
                profit_tone = "danger" if float(line.get("estimated_profit") or 0) < 0 else "ok"
            except Exception:
                profit_tone = "neutral"
        chips_row.addWidget(self._build_chip("Kar", _safe_str(line.get("estimated_profit_text")) or "-", tone=profit_tone))
        chips_row.addWidget(
            self._build_chip(
                "Durum",
                "İlan Eşleşmesi Var" if listing_title else "İlan Eşleşmesi Yok",
                tone="ok" if listing_title else "warn",
            )
        )
        chips_row.addStretch(1)
        layout.addLayout(chips_row)

        layout.addWidget(self._build_line_breakdown(line))

        for reason in list(line.get("missing_reasons") or []):
            reason_lbl = QLabel(f"- {_safe_str(reason)}")
            reason_lbl.setObjectName("RowNote")
            reason_lbl.setWordWrap(True)
            layout.addWidget(reason_lbl)
        return card

    def set_order_payload(self, *, order, payload: dict[str, Any]) -> None:
        self._order = order
        self._payload = dict(payload or {})
        self._missing_expanded = False
        self._missing_page_index = 0
        self._detail_page_indexes = {
            "sale": 0,
            "cost": 0,
        }
        self._render()

    def _toggle_missing_expanded(self) -> None:
        if not self._missing_reasons:
            return
        self._missing_expanded = not self._missing_expanded
        self._render_missing_reasons()

    def _missing_page_count(self, total_rows: int) -> int:
        per_page = max(1, int(self._MISSING_ROWS_PER_PAGE))
        return max(1, (max(0, int(total_rows)) + per_page - 1) // per_page)

    def _missing_page_bounds(self, total_rows: int) -> tuple[int, int, int, int]:
        per_page = max(1, int(self._MISSING_ROWS_PER_PAGE))
        page_count = self._missing_page_count(total_rows)
        current = max(0, min(int(self._missing_page_index), page_count - 1))
        self._missing_page_index = current
        start = current * per_page
        end = start + per_page
        return current, page_count, start, end

    def _change_missing_page(self, delta: int) -> None:
        self._missing_page_index = max(0, int(self._missing_page_index) + int(delta or 0))
        self._render_missing_reasons()

    def _build_missing_pagination_bar(self, total_rows: int) -> QFrame:
        current, page_count, _start, _end = self._missing_page_bounds(total_rows)
        bar = QFrame(self)
        bar.setObjectName("DetailPaginationBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        prev_btn = QPushButton("<")
        prev_btn.setObjectName("PageNavButton")
        prev_btn.setEnabled(current > 0)
        prev_btn.clicked.connect(lambda _checked=False: self._change_missing_page(-1))

        page_label = QLabel(f"Sayfa {current + 1} / {page_count}")
        page_label.setObjectName("PageIndicator")
        page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        next_btn = QPushButton(">")
        next_btn.setObjectName("PageNavButton")
        next_btn.setEnabled(current < page_count - 1)
        next_btn.clicked.connect(lambda _checked=False: self._change_missing_page(1))

        layout.addWidget(prev_btn, 0)
        layout.addStretch(1)
        layout.addWidget(page_label, 0)
        layout.addStretch(1)
        layout.addWidget(next_btn, 0)
        return bar

    def _render_missing_reasons(self) -> None:
        self._clear_layout(self.missing_body_layout)
        reasons = list(self._missing_reasons or [])
        self.missing_panel.setVisible(bool(reasons))
        if not reasons:
            return

        if hasattr(self, "missing_value_label"):
            self.missing_value_label.setText(str(len(reasons)))
        if hasattr(self, "missing_hint_label"):
            self.missing_hint_label.setText(
                "Eksik kayıt detaylarını kapatmak için tıkla"
                if self._missing_expanded
                else "Eksik kayıt detaylarını görmek için tıkla"
            )
        if hasattr(self, "missing_chevron_label"):
            self.missing_chevron_label.setText("^" if self._missing_expanded else "v")
        if not self._missing_expanded:
            return

        _current, page_count, start, end = self._missing_page_bounds(len(reasons))
        for reason in reasons[start:end]:
            self.missing_body_layout.addWidget(self._build_missing_reason_row(_safe_str(reason)))

        if page_count > 1:
            self.missing_body_layout.addWidget(self._build_missing_pagination_bar(len(reasons)))
        note = QLabel(f"Her sayfada {self._MISSING_ROWS_PER_PAGE} kayıt gösterilir.")
        note.setObjectName("DialogSub")
        self.missing_body_layout.addWidget(note)

    def _render(self) -> None:
        detail = dict(self._payload.get("estimated_profit_detail") or {})
        summary = dict(detail.get("summary") or {})
        results = dict(detail.get("results") or {})
        lines = list(detail.get("lines") or [])
        missing_reasons = list(self._payload.get("estimated_profit_missing_reasons") or [])
        self._missing_reasons = [_safe_str(reason) for reason in missing_reasons if _safe_str(reason)]

        order_number = _safe_str(getattr(self._order, "orderNumber", "")) or "-"
        self.title_label.setText("Sipariş Tahmini Kar Detayı")
        self.subtitle_label.setText(f"Sipariş: {order_number}")

        line_count = int(self._optional_float(summary.get("line_count")) or len(lines) or 0)
        matched_count = int(self._optional_float(summary.get("matched_line_count")) or 0)
        missing_count = len(missing_reasons)
        ready = bool(self._payload.get("estimated_profit_ready"))

        self._set_summary_card(
            "sale",
            value=_safe_str(summary.get("sale_price_text")) or _amount_text(results.get("sale_price")),
            note=(
                f"Satır: {_safe_str(summary.get('line_count_text')) or '0'}  -  "
                f"Eşleşen: {_safe_str(summary.get('matched_line_count_text')) or '0'}"
            ),
        )
        self._set_summary_card(
            "payout",
            value=_safe_str(results.get("marketplace_deductions_text")) or "-",
            note="Komisyon + kargo gibi pazaryeri kesintileri",
            tone="warn",
        )
        self._set_summary_card(
            "cost",
            value=_safe_str(results.get("total_costs_text")) or "-",
            note="Stok ve tanımlı maliyetler",
            tone="warn" if self._optional_float(results.get("total_costs")) else "neutral",
        )
        profit_tone = "muted"
        if ready:
            try:
                profit_tone = "danger" if float(self._payload.get("estimated_profit") or 0) < 0 else "ok"
            except Exception:
                profit_tone = "neutral"
        self._set_summary_card(
            "profit",
            value=_safe_str(self._payload.get("estimated_profit_text")) or "-",
            note="Satış ve maliyet farkı",
            tone=profit_tone,
        )

        self._clear_layout(self.lines_layout)

        sale_text = _safe_str(summary.get("sale_price_text")) or _amount_text(results.get("sale_price"))
        cost_text = _safe_str(results.get("total_costs_text")) or "-"
        profit_text = _safe_str(self._payload.get("estimated_profit_text")) or "-"
        sale_value_label = self._summary_cards.get("sale", {}).get("value")
        sale_note_label = self._summary_cards.get("sale", {}).get("note")
        cost_value_label = self._summary_cards.get("cost", {}).get("value")
        cost_note_label = self._summary_cards.get("cost", {}).get("note")
        if isinstance(sale_value_label, QLabel):
            sale_value_label.setText(sale_text)
        if isinstance(sale_note_label, QLabel):
            sale_note_label.setText("Satış satırlarını görmek için tıkla  ->")
        if isinstance(cost_value_label, QLabel):
            cost_value_label.setText(cost_text)
        if isinstance(cost_note_label, QLabel):
            cost_note_label.setText("Maliyet kalemlerini görmek için tıkla  ->")

        profit_value = self._optional_float(self._payload.get("estimated_profit"))
        profit_color = "#94A3B8"
        if ready and profit_value is not None:
            profit_color = "#B91C1C" if profit_value < 0 else "#15803D"
        self.profit_value_label.setText(profit_text)
        self.profit_value_label.setStyleSheet(f"font-size: 54px; font-weight: 950; color: {profit_color};")
        self.profit_panel.setProperty("danger", "true" if ready and profit_value is not None and profit_value < 0 else "false")
        self.profit_panel.style().unpolish(self.profit_panel)
        self.profit_panel.style().polish(self.profit_panel)
        if hasattr(self, "profit_icon"):
            self.profit_icon.set_colors(
                accent=profit_color if profit_color != "#94A3B8" else "#64748B",
                background="#FEE2E2" if profit_color == "#B91C1C" else "#DCFCE7" if profit_color == "#15803D" else "#F1F5F9",
            )
        self.formula_label.setText(f"{sale_text} - {cost_text} = {profit_text}")
        self._populate_detail_drawers()
        self._render_detail_drawer()

        self._render_missing_reasons()

        self._clear_layout(self.health_body_layout)
        self.health_body_layout.addWidget(
            self._build_side_stat_row("Eşleşme Durumu", f"{matched_count}/{max(line_count, 1)}", tone="ok" if matched_count == line_count and line_count > 0 else "warn")
        )
        self.health_body_layout.addWidget(
            self._build_side_stat_row(
                "Toplam Ürün Adedi",
                _safe_str(summary.get("item_quantity_total_text")) or "-",
                tone="neutral",
            )
        )
        self.health_body_layout.addWidget(
            self._build_side_stat_row("Eksik Kayıt", str(missing_count), tone="danger" if missing_count else "ok")
        )
        self.health_body_layout.addWidget(
            self._build_side_stat_row("Kâr Hesabı", "Hazır" if ready else "Bekliyor", tone="ok" if ready else "warn")
        )

        self._clear_layout(self.logic_body_layout)
        logic_notes = [
            "Sipariş satırları satış toplamını oluşturur.",
            "İlan ve stok eşleşmeleri maliyeti oluşturur.",
            "Eksik eşleşme varsa ilgili satır bloke edilir.",
        ]
        for note in logic_notes:
            self.logic_body_layout.addWidget(self._build_logic_note(note))
        self.logic_body_layout.addStretch(1)


class OrdersListDelegate(RecordWorkspaceListDelegate):
    def __init__(self, parent=None, *, on_select_button=None):
        super().__init__(parent, on_select_button=on_select_button)
        self._icon_size = ORDERS_LIST_DELEGATE_ICON_SIZE
        self._row_height = ORDERS_LIST_DELEGATE_ROW_HEIGHT
        self._hook_w = ORDERS_LIST_DELEGATE_HOOK_WIDTH
        self._hook_h = ORDERS_LIST_DELEGATE_HOOK_HEIGHT

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
        value_font = QFont(ORDERS_LIST_FONT_FAMILY, point_size)

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

        key_font = QFont(ORDERS_LIST_FONT_FAMILY, point_size, QFont.Weight.Bold)
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

        key_font = QFont(ORDERS_LIST_FONT_FAMILY, point_size, QFont.Weight.Bold)
        value_font = QFont(ORDERS_LIST_FONT_FAMILY, point_size)
        sep_font = QFont(ORDERS_LIST_FONT_FAMILY, point_size)
        sep_color = QColor(ORDERS_LIST_SEGMENT_SEPARATOR_COLOR)

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

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = option.rect.adjusted(6, 4, -6, -4)
        row = index.row()
        is_placeholder = bool(index.data(OrdersListModel.PlaceholderRole))
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected_flag = bool(index.data(OrdersListModel.SelectedRole))
        active_flag = bool(index.data(OrdersListModel.ActiveRole))
        active_visible = active_flag and self._active_visual_enabled

        if is_placeholder:
            painter.setPen(QColor(ORDERS_LIST_PLACEHOLDER_TEXT_COLOR))
            painter.setFont(QFont(ORDERS_LIST_FONT_FAMILY, ORDERS_LIST_PLACEHOLDER_FONT_SIZE))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, index.data(OrdersListModel.TitleRole) or "")
            painter.restore()
            return

        bg = QColor(ORDERS_LIST_CARD_BG_COLOR)
        border = QColor(0, 0, 0, 0)
        border_width = 1
        if selected_flag:
            bg = QColor(ORDERS_LIST_CARD_SELECTED_BG_COLOR)
            border = QColor(ORDERS_LIST_CARD_SELECTED_BORDER_COLOR)
        elif active_visible:
            bg = QColor(ORDERS_LIST_CARD_SELECTED_BG_COLOR)
            border = QColor(ORDERS_LIST_CARD_SELECTED_BORDER_COLOR)
        elif hovered:
            bg = QColor(ORDERS_LIST_CARD_HOVER_BG_COLOR)
            border = QColor(ORDERS_LIST_CARD_HOVER_BORDER_COLOR)

        order = index.data(OrdersListModel.OrderRole)
        deadline_info = summarize_order_shipping_deadline(order)
        deadline_text = str((deadline_info or {}).get("text") or "").strip()
        is_overdue = bool((deadline_info or {}).get("is_overdue"))
        if is_overdue and not selected_flag and not active_visible:
            bg = QColor(ORDERS_LIST_CARD_OVERDUE_BG_COLOR)
            border = QColor(ORDERS_LIST_CARD_OVERDUE_BORDER_COLOR)
            border_width = 1

        painter.setBrush(bg)
        painter.setPen(QPen(border, border_width))
        painter.drawRoundedRect(rect, 10, 10)

        if active_visible:
            spin_rect = rect.adjusted(1, 1, -1, -1)
            spin_pen = QPen(QColor(ORDERS_LIST_CARD_SPIN_BORDER_COLOR), 2)
            spin_pen.setStyle(Qt.PenStyle.CustomDashLine)
            spin_pen.setDashPattern([9, 6])
            spin_pen.setDashOffset(-self._spin_phase)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(spin_pen)
            painter.drawRoundedRect(spin_rect, 10, 10)

        title = index.data(OrdersListModel.TitleRole) or ""
        subtitle = index.data(OrdersListModel.SubtitleRole) or ""
        extra = index.data(OrdersListModel.ExtraRole) or ""
        icon_path = index.data(OrdersListModel.IconRole) or ""

        x = rect.left() + 10
        icon_rect = QRect(x, rect.center().y() - self._icon_size // 2, self._icon_size, self._icon_size)
        dpr = painter.device().devicePixelRatioF()
        pix = self._load_icon(icon_path, dpr)
        if pix is not None:
            pr = pix.devicePixelRatio() or 1.0
            pw = int(pix.width() / pr)
            ph = int(pix.height() / pr)
            target = QRect(0, 0, pw, ph)
            target.moveCenter(icon_rect.center())
            painter.drawPixmap(target, pix)
        else:
            painter.setBrush(QColor(ORDERS_LIST_CARD_ICON_PLACEHOLDER_COLOR))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(icon_rect, 8, 8)

        x = icon_rect.right() + 12
        side_rects = _order_right_side_rects(rect, option.widget, hook_delegate=self)
        hook_rect = side_rects["hook"]
        profit_rect = side_rects["profit"]
        text_right = hook_rect.left() - 10
        text_width = max(10, text_right - x)

        painter.setPen(QColor(ORDERS_LIST_CARD_TITLE_COLOR))
        painter.setFont(QFont(ORDERS_LIST_FONT_FAMILY, ORDERS_LIST_TITLE_FONT_SIZE, QFont.Weight.Bold))
        title_top = rect.top() + 10
        if deadline_text:
            badge_rect = QRect(x, rect.top() + 8, min(text_width, 220), 18)
            badge_fill = QColor(
                ORDERS_LIST_DEADLINE_BADGE_OVERDUE_FILL_COLOR if is_overdue else ORDERS_LIST_DEADLINE_BADGE_OK_FILL_COLOR
            )
            badge_border = QColor(
                ORDERS_LIST_DEADLINE_BADGE_OVERDUE_BORDER_COLOR if is_overdue else ORDERS_LIST_DEADLINE_BADGE_OK_BORDER_COLOR
            )
            badge_text_color = QColor(
                ORDERS_LIST_DEADLINE_BADGE_OVERDUE_TEXT_COLOR if is_overdue else ORDERS_LIST_DEADLINE_BADGE_OK_TEXT_COLOR
            )
            painter.setBrush(badge_fill)
            painter.setPen(QPen(badge_border, 1))
            painter.drawRoundedRect(badge_rect, 9, 9)
            painter.setPen(badge_text_color)
            painter.setFont(QFont(ORDERS_LIST_FONT_FAMILY, ORDERS_LIST_BADGE_FONT_SIZE, QFont.Weight.Bold))
            badge_fm = painter.fontMetrics()
            painter.drawText(
                badge_rect.adjusted(8, 0, -8, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                badge_fm.elidedText(deadline_text, Qt.TextElideMode.ElideRight, badge_rect.width() - 16),
            )
            painter.setPen(QColor(ORDERS_LIST_CARD_TITLE_COLOR))
            painter.setFont(QFont(ORDERS_LIST_FONT_FAMILY, ORDERS_LIST_TITLE_FONT_SIZE, QFont.Weight.Bold))
            title_top = badge_rect.bottom() + 5

        title_rect = QRect(x, title_top, text_width, 20)
        fm = painter.fontMetrics()
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(title, Qt.TextElideMode.ElideRight, title_rect.width()))

        sub_rect = QRect(x, title_rect.bottom() + 4, text_width, 18)
        self._draw_labeled_single_line(
            painter,
            sub_rect,
            subtitle,
            key_color=QColor(ORDERS_LIST_CARD_META_KEY_COLOR),
            value_color=QColor(ORDERS_LIST_CARD_META_VALUE_COLOR),
            point_size=ORDERS_LIST_META_FONT_SIZE,
        )

        extra_right = max(x + 40, profit_rect.left() - 10)
        extra_rect = QRect(x, sub_rect.bottom() + 2, max(10, extra_right - x), 18)
        self._draw_labeled_segments_line(
            painter,
            extra_rect,
            extra,
            key_color=QColor(ORDERS_LIST_CARD_META_KEY_COLOR),
            value_color=QColor(ORDERS_LIST_CARD_MUTED_VALUE_COLOR),
            point_size=ORDERS_LIST_META_FONT_SIZE,
        )

        self._paint_hook_button(
            painter,
            hook_rect,
            index=index,
            row=row,
            hook_selected=selected_flag,
        )

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if bool(index.data(OrdersListModel.PlaceholderRole)):
            return False
        rect = option.rect.adjusted(6, 4, -6, -4)
        view = option.widget
        hook_rect = _order_right_side_rects(rect, view, hook_delegate=self)["hook"]
        if event.type() == QEvent.Type.MouseMove:
            pos = event.position().toPoint()
            hovering = hook_rect.contains(pos)
            if hovering and self._hover_row != index.row():
                self._hover_row = index.row()
                if view:
                    view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
            elif not hovering and self._hover_row == index.row():
                self._hover_row = None
                if view:
                    view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
        if event.type() == QEvent.Type.Leave:
            if self._hover_row is not None:
                self._hover_row = None
                if view:
                    view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if hook_rect.contains(pos):
                self._pressed_row = index.row()
                if view:
                    view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
                return True
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            was_pressed = self._pressed_row == index.row()
            self._pressed_row = None
            if view:
                view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
            if was_pressed and hook_rect.contains(pos):
                self._mark_view_action_click_handled(view)
                current = bool(index.data(OrdersListModel.SelectedRole))
                next_selected = not current
                return bool(self._handle_hook_activated(model, index, next_selected))
        return super().editorEvent(event, model, option, index)

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        _ = option
        _ = index
        return QSize(0, self._row_height)


class OrdersListWidget(QListView):
    selection_changed = pyqtSignal()
    selection_state_changed = pyqtSignal()
    page_changed = pyqtSignal(int, int, int, int)
    order_clicked = pyqtSignal(object)
    selection_button_clicked = pyqtSignal(object, bool)
    blank_area_clicked = pyqtSignal()
    data_loaded = pyqtSignal(list)

    def __init__(
        self,
        parent=None,
        *,
        load_callable=None,
        decorate_orders_cb=None,
        open_profit_detail_cb=None,
        loading_message: str = "Siparişler yükleniyor...",
        empty_placeholder_text: str = ORDERS_LIST_EMPTY_TEXT,
        emit_global_orders_loaded: bool = True,
    ):
        super().__init__(parent)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setMouseTracking(True)
        self.setSpacing(6)
        self.setUniformItemSizes(False)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

        self.orders: list = []
        self.filtered_orders: list = []

        self.status_filter: str = "all"
        self.page_size: int = 20
        self.current_page: int = 1

        self.auto_build_on_reload: bool = True
        self._suppress_click_once = False
        self._active_order_number: str = ""
        self._active_spin_allowed: bool = True
        self._active_border_animation_enabled: bool = False
        self._guide_select_animation_enabled: bool = False
        self._reload_seq: int = 0
        self._loading_state_callback = None
        self._loading_geometry_sync_callback = None
        self._default_loading_message = str(loading_message or "Siparişler yükleniyor...")
        self._load_callable = load_callable
        self._decorate_orders_cb = decorate_orders_cb if callable(decorate_orders_cb) else None
        self._open_profit_detail_cb = open_profit_detail_cb if callable(open_profit_detail_cb) else None
        self._emit_global_orders_loaded = bool(emit_global_orders_loaded)
        self._external_selection_handler_enabled = False
        self._last_selection_signature: tuple[str, ...] = tuple()
        self._inline_profit_controls: dict[int, ProfitDetailControl] = {}
        self._startup_layout_synced = False
        self._initial_reload_queued = False
        self._reload_pending = False
        self._is_shutting_down = False
        self.reload_worker: SyncWorker | None = None

        self._model = OrdersListModel(
            parent=self,
            on_selection_changed=self._emit_selection_signals_if_needed,
            empty_placeholder_text=empty_placeholder_text,
        )
        self._delegate = OrdersListDelegate(self, on_select_button=self._on_select_button_clicked)
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self.clicked.connect(self._on_row_clicked)

        self._active_border_timer = QTimer(self)
        self._active_border_timer.setInterval(42)
        self._active_border_timer.timeout.connect(self._tick_active_border_animation)
        self._deadline_refresh_timer = QTimer(self)
        self._deadline_refresh_timer.setInterval(60_000)
        self._deadline_refresh_timer.timeout.connect(self.viewport().update)
        self._deadline_refresh_timer.start()
        try:
            self.verticalScrollBar().rangeChanged.connect(
                lambda *_: QTimer.singleShot(0, self._position_inline_profit_controls)
            )
        except Exception:
            pass

        if self._emit_global_orders_loaded:
            order_signals.orders_changed.connect(self.reload_orders)

    def shutdown_workers(self, wait_ms: int = 1500) -> None:
        self._is_shutting_down = True
        self._reload_pending = False
        self._reload_seq += 1
        for timer in (self._active_border_timer, self._deadline_refresh_timer):
            try:
                timer.stop()
            except Exception:
                pass
        if self._emit_global_orders_loaded:
            try:
                order_signals.orders_changed.disconnect(self.reload_orders)
            except Exception:
                pass
        worker = self.reload_worker
        self.reload_worker = None
        if worker is None:
            return
        try:
            worker.requestInterruption()
        except Exception:
            pass
        try:
            if worker.isRunning():
                worker.wait(max(0, int(wait_ms)))
        except Exception:
            pass
        try:
            if not worker.isRunning():
                worker.deleteLater()
        except Exception:
            pass

    def resume_workers(self) -> None:
        if not self._is_shutting_down:
            return
        self._is_shutting_down = False
        try:
            if not self._deadline_refresh_timer.isActive():
                self._deadline_refresh_timer.start()
        except Exception:
            pass
        if self._emit_global_orders_loaded:
            try:
                order_signals.orders_changed.disconnect(self.reload_orders)
            except Exception:
                pass
            try:
                order_signals.orders_changed.connect(self.reload_orders)
            except Exception:
                pass

    def set_loading_overlay_hooks(self, *, set_busy=None, sync_geometry=None) -> None:
        self._loading_state_callback = set_busy if callable(set_busy) else None
        self._loading_geometry_sync_callback = sync_geometry if callable(sync_geometry) else None

    def sync_loading_overlay_geometry(self) -> None:
        if callable(self._loading_geometry_sync_callback):
            try:
                self._loading_geometry_sync_callback()
            except Exception:
                return
        return

    def set_list_loading(self, busy: bool, message: str | None = None) -> None:
        text = str(message or self._default_loading_message)
        if callable(self._loading_state_callback):
            try:
                self._loading_state_callback(bool(busy), text)
            except Exception:
                return
        return

    def get_total_pages(self) -> int:
        total = len(self.filtered_orders or [])
        if total <= 0:
            return 1
        return (total + self.page_size - 1) // self.page_size

    def set_page_size(self, size: int):
        if size <= 0:
            return
        self.page_size = size
        self.current_page = 1
        self._safe_build(self.filtered_orders)

    def go_to_page(self, page: int):
        total_pages = self.get_total_pages()
        page = max(1, min(page, total_pages))
        self.current_page = page
        self._safe_build(self.filtered_orders)

    def next_page(self):
        self.go_to_page(self.current_page + 1)

    def prev_page(self):
        self.go_to_page(self.current_page - 1)

    def shown_count(self) -> int:
        return self._model.visible_count() if self._model else 0

    def total_record_count(self) -> int:
        return len(self.filtered_orders or [])

    @staticmethod
    def _order_number_of(order) -> str:
        if bool(getattr(order, "_is_return", False)):
            return str(
                getattr(order, "claimId", "")
                or getattr(order, "claimNumber", "")
                or getattr(order, "orderNumber", "")
                or ""
            ).strip()
        return str(getattr(order, "orderNumber", "") or "").strip()

    def _find_row_by_order_number(self, order_number: str) -> int:
        needle = str(order_number or "").strip()
        if not needle:
            return -1
        row = self._model.row_for_order_number(needle)
        if row >= 0:
            return row
        for row in range(self._model.rowCount()):
            item = self._model.item_at(row)
            if not item or item.get("placeholder"):
                continue
            order = item.get("order")
            current = self._order_number_of(order)
            if current == needle:
                return row
        return -1

    def _reapply_active_row(self) -> None:
        row = self._find_row_by_order_number(self._active_order_number)
        self._model.set_active_row(row)
        self._set_active_border_animation_enabled(row >= 0 and self._active_spin_allowed)

    def set_active_order(self, order) -> None:
        self._active_order_number = self._order_number_of(order)
        self._reapply_active_row()

    def clear_active_order(self) -> None:
        self._active_order_number = ""
        self._model.clear_active_row()
        self._set_active_border_animation_enabled(False)

    def set_active_spin_allowed(self, allowed: bool) -> None:
        self._active_spin_allowed = bool(allowed)
        self._delegate.set_active_visual_enabled(self._active_spin_allowed)
        active_row = self._find_row_by_order_number(self._active_order_number)
        self._set_active_border_animation_enabled(active_row >= 0 and self._active_spin_allowed)

    def _set_active_border_animation_enabled(self, enabled: bool) -> None:
        self._active_border_animation_enabled = bool(enabled)
        self._sync_border_animation_timer()

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self._guide_select_animation_enabled = bool(enabled)
        self._delegate.set_guide_select_enabled(self._guide_select_animation_enabled)
        self._sync_border_animation_timer()

    def set_external_selection_handler_enabled(self, enabled: bool) -> None:
        self._external_selection_handler_enabled = bool(enabled)

    def _selection_signature(self) -> tuple[str, ...]:
        selected_keys: list[str] = []
        for index, order in enumerate(self.filtered_orders or []):
            if not bool(getattr(order, "_selected", False)):
                continue
            key = self._order_number_of(order)
            if not key:
                key = f"row:{index}"
            selected_keys.append(key)
        return tuple(sorted(selected_keys))

    def _emit_selection_signals_if_needed(self, *_args, force: bool = False) -> None:
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
            self.viewport().update()
            return
        active_row = self._find_row_by_order_number(self._active_order_number)
        if active_row < 0:
            return
        index = self._model.index(active_row)
        rect = self.visualRect(index)
        if rect.isValid() and not rect.isNull():
            self.viewport().update(rect.adjusted(-2, -2, 2, 2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_dynamic_row_width()
        self.sync_loading_overlay_geometry()

    def sync_dynamic_row_width(self) -> None:
        try:
            self.doItemsLayout()
            self._position_inline_profit_controls()
            self.viewport().update()
        except Exception:
            return

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_loading_overlay_geometry()
        if not self._startup_layout_synced:
            self._startup_layout_synced = True
            QTimer.singleShot(0, self.sync_dynamic_row_width)
            QTimer.singleShot(90, self.sync_dynamic_row_width)
        if not self.orders and not self._initial_reload_queued:
            self._initial_reload_queued = True
            QTimer.singleShot(0, self._run_initial_reload)

    def _run_initial_reload(self) -> None:
        self._initial_reload_queued = False
        if self.isVisible() and not self.orders:
            self.reload_orders()

    @staticmethod
    def _iter_runtime_datetime_attrs(order) -> list[str]:
        try:
            state = vars(order)
        except TypeError:
            state = getattr(order, "__dict__", {}) or {}

        attrs: list[str] = []
        for attr in state.keys():
            if not isinstance(attr, str) or attr.startswith("_"):
                continue
            lower = attr.lower()
            if "date" in lower or "time" in lower:
                attrs.append(attr)
        return attrs

    def _normalize_epoch_dates(self, orders: list):
        for o in orders:
            for attr in self._iter_runtime_datetime_attrs(o):
                try:
                    val = getattr(o, attr)
                except AttributeError:
                    continue

                ts = None
                if isinstance(val, (int, float)):
                    ts = val
                elif isinstance(val, str) and val.isdigit():
                    try:
                        ts = int(val)
                    except ValueError:
                        ts = None

                if ts is None or ts < 10 ** 9:
                    continue

                try:
                    if ts > 10 ** 11:
                        dt = datetime.fromtimestamp(ts / 1000)
                    else:
                        dt = datetime.fromtimestamp(ts)
                    setattr(o, attr, dt)
                except Exception:
                    continue

    def reload_orders(self):
        if self._is_shutting_down:
            return
        worker = getattr(self, "reload_worker", None)
        if worker is not None and worker.isRunning():
            self._reload_pending = True
            return
        self._reload_pending = False
        self._reload_seq += 1
        seq = int(self._reload_seq)
        defer_loading_close_to_filter = {"value": not bool(getattr(self, "auto_build_on_reload", True))}
        # Yeni çekim sırasında eski (muhtemelen farklı filtreli) listeyi göstermeyelim.
        self.filtered_orders = []
        self.current_page = 1
        self._safe_build([])
        self.set_list_loading(True)
        load_fn = self._load_callable if callable(self._load_callable) else load_ready_to_ship_orders
        worker = SyncWorker(load_fn, parent=self)
        self.reload_worker = worker

        def handle_reload_result(result: Result):
            if self._is_shutting_down:
                return
            if seq != self._reload_seq:
                return
            if not result.success:
                defer_loading_close_to_filter["value"] = False
                MessageHandler.show(self, result, only_errors=True)
                self.set_list_loading(False)
                return

            self.orders = result.data.get("records", []) or []
            self._normalize_epoch_dates(self.orders)

            self.filtered_orders = self.orders
            self.current_page = 1

            if getattr(self, "auto_build_on_reload", True):
                defer_loading_close_to_filter["value"] = False
                self._safe_build(self.filtered_orders)
                self.set_list_loading(False)
            else:
                # auto_build kapalıysa (OrdersManagerWindow), görünüm filtre worker'ı
                # ile kuruluyor; loading overlay bu adım tamamlanana kadar açık kalsın.
                defer_loading_close_to_filter["value"] = True

            self.data_loaded.emit(self.filtered_orders)
            if self._emit_global_orders_loaded:
                order_signals.orders_loaded.emit(self.filtered_orders)

        def _handle_reload_finished():
            if self._is_shutting_down:
                try:
                    worker.deleteLater()
                except Exception:
                    pass
                return
            if getattr(self, "reload_worker", None) is worker:
                self.reload_worker = None
            if seq == self._reload_seq:
                if not defer_loading_close_to_filter["value"]:
                    self.set_list_loading(False)
            if self._reload_pending:
                self._reload_pending = False
                QTimer.singleShot(0, self.reload_orders)
            worker.deleteLater()

        worker.result_ready.connect(handle_reload_result)
        worker.finished.connect(_handle_reload_finished)
        worker.start()

    def apply_filter_result(self, filtered_orders: list):
        self.filtered_orders = filtered_orders if isinstance(filtered_orders, list) else list(filtered_orders or [])
        self.current_page = 1
        self._safe_build(self.filtered_orders)

    def _safe_build(self, orders: list | None = None):
        try:
            if orders is not None:
                self.filtered_orders = orders if isinstance(orders, list) else list(orders or [])
            self._build_page()
        except Exception as e:
            MessageHandler.show(self, Result.fail(map_error_to_message(e), error=e), only_errors=True)

    def _build_page(self):
        total = len(self.filtered_orders or [])
        if total <= 0:
            self._model.set_orders([])
            self._rebuild_inline_profit_controls()
            self._set_active_border_animation_enabled(False)
            self._emit_selection_signals_if_needed()
            self.page_changed.emit(1, 1, 0, 0)
            return

        page_size = max(1, int(getattr(self, "page_size", 20)))
        total_pages = (total + page_size - 1) // page_size
        self.current_page = max(1, min(self.current_page, total_pages))

        start_idx = (self.current_page - 1) * page_size
        end_idx = min(start_idx + page_size, total)
        show_list = self.filtered_orders[start_idx:end_idx]
        if self._decorate_orders_cb:
            try:
                self._decorate_orders_cb(show_list)
            except Exception:
                pass
        self._model.set_orders(show_list)
        self._rebuild_inline_profit_controls()
        self._reapply_active_row()
        self._emit_selection_signals_if_needed()
        self.page_changed.emit(self.current_page, total_pages, total, len(show_list))
        QTimer.singleShot(0, self._position_inline_profit_controls)

    def _rebuild_inline_profit_controls(self) -> None:
        for widget in self._inline_profit_controls.values():
            widget.setParent(None)
            widget.deleteLater()
        self._inline_profit_controls = {}

        for row in range(self._model.rowCount()):
            item = self._model.item_at(row) or {}
            if item.get("placeholder"):
                continue
            ctrl = ProfitDetailControl(self.viewport())
            ctrl.set_profit(
                item.get("estimated_profit_text") or "-",
                bool(item.get("estimated_profit_ready")),
                item.get("estimated_profit"),
            )
            ctrl.detailRequested.connect(lambda r=row: self._open_profit_detail_for_row(r))
            self._inline_profit_controls[row] = ctrl

    def _open_profit_detail_for_row(self, row: int) -> None:
        if not self._open_profit_detail_cb:
            return
        item = self._model.item_at(row) or {}
        order = item.get("order")
        if order is None:
            return
        self.set_active_order(order)
        QTimer.singleShot(0, lambda current=order: self._open_profit_detail_cb(current))

    def _position_inline_profit_controls(self) -> None:
        for row in range(self._model.rowCount()):
            ctrl = self._inline_profit_controls.get(row)
            if ctrl is None:
                continue
            idx = self._model.index(row)
            rect = self.visualRect(idx)
            if rect.isNull() or rect.height() <= 0:
                ctrl.setVisible(False)
                continue
            row_rect = rect.adjusted(6, 4, -6, -4)
            profit_rect = _order_right_side_rects(row_rect, self, hook_delegate=self._delegate)["profit"]
            ctrl.setGeometry(profit_rect)
            ctrl.setVisible(True)
            ctrl.raise_()

    def clear_other_selections(self, keep_widget):
        # tek seçim modu için; şimdilik kullanılmıyor
        return

    def get_selected_orders(self) -> list:
        return [o for o in (self.filtered_orders or []) if getattr(o, "_selected", False)]

    def get_selected_records(self) -> list:
        return self.get_selected_orders()

    def clear_selected_records(self) -> None:
        changed = False
        for order in self.filtered_orders or []:
            if bool(getattr(order, "_selected", False)):
                setattr(order, "_selected", False)
                changed = True
        if changed:
            self._safe_build(self.filtered_orders)
        else:
            self._emit_selection_signals_if_needed(force=True)

    def select_all_filtered_records(self) -> None:
        changed = False
        for order in self.filtered_orders or []:
            if not bool(getattr(order, "_selected", False)):
                setattr(order, "_selected", True)
                changed = True
        if changed:
            self._safe_build(self.filtered_orders)
        else:
            self._emit_selection_signals_if_needed(force=True)

    def _on_row_clicked(self, index: QModelIndex):
        try:
            if self._suppress_click_once:
                self._suppress_click_once = False
                return
            if not index.isValid():
                return
            if bool(index.data(OrdersListModel.PlaceholderRole)):
                return
            order = index.data(OrdersListModel.OrderRole)
            if order is None:
                return
            self.set_active_order(order)
            self.order_clicked.emit(order)
        except Exception:
            return

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            if not index.isValid():
                self.clear_active_order()
                self.blank_area_clicked.emit()
        super().mousePressEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._position_inline_profit_controls()

    def _on_select_button_clicked(self, index: QModelIndex, selected: bool):
        try:
            self._suppress_click_once = True
            if not index.isValid():
                return False
            if bool(index.data(OrdersListModel.PlaceholderRole)):
                return False
            order = index.data(OrdersListModel.OrderRole)
            if order is None:
                return False
            self.set_active_order(order)
            if not self._external_selection_handler_enabled:
                self.set_order_selected(order, bool(selected))
            self.selection_button_clicked.emit(order, bool(selected))
            return True
        except Exception:
            return False

    def set_order_selected(self, order, selected: bool) -> None:
        if order is None:
            return
        setattr(order, "_selected", bool(selected))
        row = self._find_row_by_order_number(self._order_number_of(order))
        if row >= 0:
            self._model.set_selected(row, bool(selected))
        self._emit_selection_signals_if_needed()


# ============================================================
# 2. OrdersManagerWindow
# ============================================================

class OrdersManagerWindow(QWidget):
    """
    Revize v3 (UI/UX düzeltmeleri):
    1. Müşteri adı inputu ile müşteri labelı yan yana/aynı blok
    2. Kargo dropdown ile sipariş no daha yakın (layout akışı düzeltildi)
    3. Tarih checkbox zorunluluğu kalktı (always enabled)
    4. Default tarih aralığı: son 30 gün
    5. Tarih formatı yıl görünecek: dd.MM.yyyy
    6. Durum label ile dropdown arası boşluk kapatıldı
    7. Tümünü Seç / Seçimi Kaldır ayrı yuvarlak bar görünümü kalktı
    8. Alt bar tek satır: [solda bulk] [ortada pagination] [sağda sayfa başına]
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self._window_mode = "orders"
        self._returns_remote_signature: tuple[str, str] | None = None
        self._entity_plural = "Siparişler"
        self._entity_singular = "Sipariş"

        self.setWindowTitle(self._entity_plural)
        self.setWindowIcon(QIcon(str(ORDERS_MANAGER_ICON_PATH)))
        self.setMinimumSize(ORDERS_WINDOW_MIN_WIDTH, ORDERS_WINDOW_MIN_HEIGHT)
        flags = self.windowFlags()
        flags |= Qt.WindowType.WindowMinMaxButtonsHint
        flags |= Qt.WindowType.WindowCloseButtonHint
        flags &= ~Qt.WindowType.WindowContextHelpButtonHint
        self.setWindowFlags(flags)
        self.setGeometry(ORDERS_WINDOW_X, ORDERS_WINDOW_Y, ORDERS_WINDOW_MIN_WIDTH, ORDERS_WINDOW_MIN_HEIGHT)

        self._setup_styles()

        self._left_stick_size = ORDERS_WORKSPACE_LEFT_STICK_SIZE
        self._left_collapse_trigger = ORDERS_WORKSPACE_LEFT_COLLAPSE_TRIGGER
        self._order_items_cache: OrderedDict[str, list[dict]] = OrderedDict()
        self._order_profit_catalog: dict[str, Any] | None = None
        self._order_profit_catalog_account_ids: set[int] = set()
        self._order_profit_worker: SyncWorker | None = None
        self._order_profit_request_seq: int = 0
        self._pending_profit_detail_key: str = ""
        self._order_profit_window: OrderProfitBreakdownWindow | None = None
        self._active_order = None
        self._selection_mode = "detail"
        self._filter_request_seq = 0
        self._last_applied_filter_signature: tuple[object, ...] | None = None
        self._last_workspace_state_signature: tuple[object, ...] | None = None
        self._date_range_user_overridden: bool = False
        self._orders_source_signature: tuple[str, str, str, str] = ("", "", "", "")
        self._closing: bool = False
        self.reload_worker: SyncWorker | None = None
        self.filter_worker: SyncWorker | None = None
        self._filter_workers: list[SyncWorker] = []
        self._profit_workers: list[SyncWorker] = []
        self._profit_pending_keys: set[str] = set()
        self._cargo_change_worker: SyncWorker | None = None
        self._bulk_cargo_change_worker: SyncWorker | None = None

        self._init_scaffold_orders_workspace()
        QTimer.singleShot(450, self._prewarm_order_profit_window)

    def ensure_order_numbers_loaded(self, order_numbers: list[str] | tuple[str, ...]) -> Result:
        normalized_numbers = [
            str(row or "").strip()
            for row in (order_numbers or [])
            if str(row or "").strip()
        ]
        if not normalized_numbers:
            return Result.ok("Sipariş numarası boş.", close_dialog=False, data={"records": []})

        existing_numbers = {
            str(getattr(order, "orderNumber", "") or "").strip()
            for order in (self.list_widget.orders or [])
            if str(getattr(order, "orderNumber", "") or "").strip()
        }
        missing_numbers = [number for number in normalized_numbers if number not in existing_numbers]
        if not missing_numbers:
            return Result.ok("Siparişler zaten yüklü.", close_dialog=False, data={"records": []})

        res = load_orders_by_numbers(missing_numbers)
        if not res.success:
            return res

        fetched = list((res.data or {}).get("records", []) or [])
        if not fetched:
            return Result.ok("Sipariş bulunamadı.", close_dialog=False, data={"records": []})

        self.list_widget._normalize_epoch_dates(fetched)
        merged: list = []
        seen_keys: set[tuple[object, str]] = set()
        for order in [*fetched, *(self.list_widget.orders or [])]:
            key = (
                getattr(order, "api_account_id", None),
                str(getattr(order, "orderNumber", "") or "").strip(),
            )
            if not key[1] or key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(order)

        self.list_widget.orders = merged
        self.list_widget.filtered_orders = merged
        self._last_applied_filter_signature = None
        self.list_widget.data_loaded.emit(self.list_widget.filtered_orders)
        return Result.ok("Siparişler pencereye eklendi.", close_dialog=False, data={"records": fetched})

    def _init_scaffold_orders_workspace(self) -> None:
        root_layout = self.layout()
        if root_layout is None:
            root_layout = QVBoxLayout(self)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)
        self._workspace = RecordWorkspaceScaffold(
            self,
            left_title="",
            left_subtitle="",
            filters_title="Filtreler",
            filters_subtitle="",
            records_title=self._entity_plural,
            show_editor_actions_card=False,
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
            shell_kwargs={
                **ORDERS_WORKSPACE_SHELL_KWARGS,
                "left_stick_size": self._left_stick_size,
                "left_collapse_trigger": self._left_collapse_trigger,
            },
            sidebar_buttons=(
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": str(ui_text("orders.sidebar.edit_tooltip", ORDERS_SIDEBAR_EDIT_TOOLTIP)),
                    "icon_path": str(ORDERS_SIDEBAR_EDIT_ICON_PATH),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "bulk",
                    "text": "",
                    "tooltip": str(ui_text("orders.sidebar.bulk_tooltip", ORDERS_SIDEBAR_BULK_TOOLTIP)),
                    "icon_path": str(ORDERS_SIDEBAR_BULK_ICON_PATH),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
            ),
            page_size_options=ORDERS_WORKSPACE_PAGE_SIZE_OPTIONS,
        )
        self._workspace.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root_layout.addWidget(self._workspace, 1)
        self._workspace.editor_scroll.setViewportMargins(0, 0, 12, 0)
        self._workspace.left_card.setObjectName("Card")
        self._workspace.filters_card.setObjectName("Card")
        self._workspace.filters_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._workspace.records_card.setObjectName("Card")
        self._workspace_shell = self._workspace.shell
        self._orders_splitter = self._workspace_shell.splitter
        self._orders_splitter.setCollapsible(0, True)
        self._orders_splitter.setCollapsible(1, False)

        self.list_widget = OrdersListWidget(
            self._workspace.records_card,
            load_callable=self._load_records_for_window,
            decorate_orders_cb=self._decorate_orders_with_profit,
            open_profit_detail_cb=self._open_order_profit_detail,
            loading_message=ORDERS_ENTITY_LOADING_TEMPLATE.format(entity_plural=self._entity_plural),
            empty_placeholder_text=ORDERS_ENTITY_EMPTY_TEMPLATE.format(entity_singular=self._entity_singular.lower()),
            emit_global_orders_loaded=(self._window_mode == "orders"),
        )
        self.list_widget.auto_build_on_reload = False
        self.list_widget.selection_changed.connect(self._on_selection_changed)
        self.list_widget.page_changed.connect(lambda *_: self._update_pagination_ui())
        try:
            self.list_widget.verticalScrollBar().valueChanged.connect(self._sync_bulk_guidance_overlays_geometry)
            self.list_widget.horizontalScrollBar().valueChanged.connect(self._sync_bulk_guidance_overlays_geometry)
        except Exception:
            pass
        try:
            model = self.list_widget.model()
            if model is not None:
                model.modelReset.connect(self._sync_bulk_guidance_overlays_geometry)
                model.layoutChanged.connect(self._sync_bulk_guidance_overlays_geometry)
                model.rowsInserted.connect(lambda *_: self._sync_bulk_guidance_overlays_geometry())
                model.rowsRemoved.connect(lambda *_: self._sync_bulk_guidance_overlays_geometry())
        except Exception:
            pass

        selection_card = QWidget(self._workspace.editor_host)
        self._selection_card = selection_card
        selection_card.setObjectName("OrdersSelectionHost")
        selection_card.setStyleSheet("background: transparent;")
        selection_layout = QVBoxLayout(selection_card)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        selection_layout.setSpacing(8)

        selection_title_default = "İade Detayı" if self._window_mode == "returns" else "Sipariş Düzenle"
        self.selection_title = QLabel(str(ui_text("orders.selection_panel.title", selection_title_default)))
        self.selection_title.setObjectName("CardTitle")
        self.selection_title.hide()
        selection_layout.addWidget(self.selection_title)

        self.selection_stack = QStackedWidget(selection_card)
        selection_layout.addWidget(self.selection_stack)

        empty_page = QWidget(selection_card)
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setContentsMargins(0, 4, 0, 0)
        empty_layout.setSpacing(8)
        empty_hint_default = (
            "İade seçildiğinde detay paneli burada açılır."
            if self._window_mode == "returns"
            else "Sipariş seçildiğinde detay veya toplu işlem paneli burada açılır."
        )
        empty_text = QLabel(str(ui_text("orders.selection_panel.empty_hint", empty_hint_default)))
        empty_text.setObjectName("Muted")
        empty_text.setWordWrap(True)
        empty_layout.addWidget(empty_text)
        empty_layout.addStretch(1)
        self.selection_stack.addWidget(empty_page)

        detail_page = QWidget(selection_card)
        detail_layout = QVBoxLayout(detail_page)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(8)

        detail_top = QWidget(detail_page)
        detail_top_layout = QVBoxLayout(detail_top)
        detail_top_layout.setContentsMargins(0, 0, 0, 0)
        detail_top_layout.setSpacing(8)

        def _value_label() -> QLabel:
            lbl = QLabel(orders_ui.ORDERS_EMPTY_VALUE_TEXT)
            lbl.setObjectName("Muted")
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setWordWrap(True)
            return lbl

        detail_info_default = "İade Bilgileri" if self._window_mode == "returns" else "Sipariş Bilgileri"
        detail_info_title = QLabel(str(ui_text("orders.selection_panel.detail.info_title", detail_info_default)))
        detail_info_title.setObjectName("CardTitle")
        detail_top_layout.addWidget(detail_info_title)

        detail_form = QFormLayout()
        detail_form.setContentsMargins(0, 0, 0, 0)
        detail_form.setHorizontalSpacing(8)
        detail_form.setVerticalSpacing(6)

        self.detail_order_no = _value_label()
        self.detail_customer = _value_label()
        self.detail_phone = _value_label()
        self.detail_status = _value_label()
        self.detail_cargo = _value_label()
        self.detail_tracking_no = _value_label()
        self.detail_amount = _value_label()
        self.detail_date = _value_label()
        self.detail_address = _value_label()

        detail_order_no_default = "İade No" if self._window_mode == "returns" else "Sipariş No"
        detail_status_default = "İade Durumu" if self._window_mode == "returns" else "Durum"
        self.detail_order_no_label = QLabel(str(ui_text("orders.selection_panel.detail.order_no", detail_order_no_default)))
        self.detail_status_label = QLabel(str(ui_text("orders.selection_panel.detail.status", detail_status_default)))
        detail_form.addRow(self.detail_order_no_label, self.detail_order_no)
        detail_form.addRow(str(ui_text("orders.selection_panel.detail.customer", "Müşteri")), self.detail_customer)
        detail_form.addRow(str(ui_text("orders.selection_panel.detail.phone", "Telefon")), self.detail_phone)
        detail_form.addRow(self.detail_status_label, self.detail_status)
        detail_form.addRow(str(ui_text("orders.selection_panel.detail.cargo", "Kargo")), self.detail_cargo)
        detail_form.addRow(str(ui_text("orders.selection_panel.detail.tracking_no", "Takip No")), self.detail_tracking_no)
        detail_form.addRow(str(ui_text("orders.selection_panel.detail.date", "Tarih")), self.detail_date)
        detail_form.addRow(str(ui_text("orders.selection_panel.detail.amount", "Tutar")), self.detail_amount)
        detail_form.addRow(str(ui_text("orders.selection_panel.detail.address", "Adres")), self.detail_address)
        detail_top_layout.addLayout(detail_form)

        detail_items_default = "İade Ürünleri" if self._window_mode == "returns" else "Sipariş Ürünleri"
        detail_items_title = QLabel(str(ui_text("orders.selection_panel.detail.items_title", detail_items_default)))
        detail_items_title.setObjectName("CardTitle")
        detail_top_layout.addWidget(detail_items_title)

        self.detail_items_table = QTableWidget(0, 5, detail_page)
        headers = ui_text("orders.selection_panel.detail.items_headers", ["Ürün", "SKU", "Barkod", "Adet", "Tutar"])
        if not isinstance(headers, list) or len(headers) != 5:
            headers = ["Ürün", "SKU", "Barkod", "Adet", "Tutar"]
        self.detail_items_table.setHorizontalHeaderLabels([str(h) for h in headers])
        self.detail_items_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.detail_items_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detail_items_table.setAlternatingRowColors(True)
        self.detail_items_table.verticalHeader().setVisible(False)
        self.detail_items_table.setMinimumHeight(170)
        header = self.detail_items_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        detail_top_layout.addWidget(self.detail_items_table)

        self.detail_items_hint = QLabel(str(ui_text("orders.selection_panel.detail.items_empty", "Bu sipariş için ürün satırı bulunamadı.")))
        self.detail_items_hint.setObjectName("Muted")
        self.detail_items_hint.setWordWrap(True)
        detail_top_layout.addWidget(self.detail_items_hint)
        detail_layout.addWidget(detail_top)

        detail_bottom = QWidget(detail_page)
        detail_bottom_layout = QVBoxLayout(detail_bottom)
        detail_bottom_layout.setContentsMargins(0, 0, 0, 0)
        detail_bottom_layout.setSpacing(8)

        self.detail_tabs = GlowTabWidget(detail_bottom)
        self.detail_tabs.set_tab_palette(
            container_bg="#DBEAFE",
            container_border="#93C5FD",
            indicator="#22C55E",
            text_active="#166534",
            text_inactive="#1D4ED8",
            text_hover="#0F172A",
        )
        detail_bottom_layout.addWidget(self.detail_tabs)
        self.detail_tab_hint = QLabel(orders_ui.ORDERS_DETAIL_NO_ACTION_TEXT)
        self.detail_tab_hint.setObjectName("Muted")
        self.detail_tab_hint.setWordWrap(True)
        self.detail_tab_hint.hide()
        detail_bottom_layout.addWidget(self.detail_tab_hint)

        cargo_tab = QWidget(self.detail_tabs)
        cargo_tab_layout = QVBoxLayout(cargo_tab)
        cargo_tab_layout.setContentsMargins(0, 0, 0, 0)
        cargo_tab_layout.setSpacing(8)
        cargo_change_title = QLabel(str(ui_text("orders.selection_panel.detail.cargo_change_title", "Kargo Firması Değişikliği")))
        cargo_change_title.setObjectName("CardTitle")
        cargo_tab_layout.addWidget(cargo_change_title)
        cargo_change_row = QVBoxLayout()
        cargo_change_row.setSpacing(8)
        self.detail_cargo_provider_select = SwitchSelectWidget(
            multi=False,
            include_all=False,
            empty_text=str(ui_text("orders.selection_panel.detail.cargo_change_empty", "Kargo firması seç")),
        )
        self.detail_cargo_provider_select.setMinimumWidth(0)
        self.detail_cargo_provider_select.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for row in list_changeable_cargo_providers():
            code = str(row.get("code") or "").strip()
            name = str(row.get("name") or "").strip()
            if code and name:
                self.detail_cargo_provider_select.addItem(f"{name} ({code})", data=code)
        self.btn_change_cargo_provider = QPushButton(
            str(ui_text("orders.selection_panel.detail.cargo_change_button", "Kargo Firmasını Güncelle"))
        )
        self.btn_change_cargo_provider.setObjectName("Primary")
        self.btn_change_cargo_provider.setStyleSheet(
            """
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: 1px solid #2563EB;
                border-radius: 10px;
                padding: 7px 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
                border-color: #1D4ED8;
            }
            QPushButton:disabled {
                background-color: #DBEAFE;
                color: #1D4ED8;
                border: 1px solid #93C5FD;
            }
            """
        )
        self.btn_change_cargo_provider.setMinimumHeight(40)
        self.btn_change_cargo_provider.setMinimumWidth(0)
        self.btn_change_cargo_provider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_change_cargo_provider.setEnabled(False)
        self.btn_change_cargo_provider.clicked.connect(self._on_change_cargo_provider_clicked)
        cargo_change_row.addWidget(self.detail_cargo_provider_select)
        cargo_change_row.addWidget(self.btn_change_cargo_provider)
        cargo_tab_layout.addLayout(cargo_change_row)
        cargo_change_hint = QLabel(
            str(
                ui_text(
                    "orders.selection_panel.detail.cargo_change_hint",
                    "Not: Trendyol kargo sağlayıcı değişikliğinde paket bazlı ve 5 dakikada 1 kez kısıtı bulunur.",
                )
            )
        )
        cargo_change_hint.setObjectName("Muted")
        cargo_change_hint.setWordWrap(True)
        cargo_tab_layout.addWidget(cargo_change_hint)
        cargo_tab_layout.addStretch(1)

        print_tab = QWidget(self.detail_tabs)
        print_tab_layout = QVBoxLayout(print_tab)
        print_tab_layout.setContentsMargins(0, 0, 0, 0)
        print_tab_layout.setSpacing(8)
        print_title = QLabel(str(ui_text("orders.selection_panel.detail.print_tab_title", "Yazdırma")))
        print_title.setObjectName("CardTitle")
        print_tab_layout.addWidget(print_title)
        print_hint = QLabel(
            str(ui_text("orders.selection_panel.detail.print_tab_hint", "Seçili sipariş için etiket/yazdırma penceresini aç."))
        )
        print_hint.setObjectName("Muted")
        print_hint.setWordWrap(True)
        print_tab_layout.addWidget(print_hint)
        self.btn_detail_print = ActionPulseButton(
            text=str(ui_text("orders.selection_panel.detail.print_button", "Yazdır")),
            center_text=True,
        )
        self.btn_detail_print.setEnabled(False)
        self.btn_detail_print.clicked.connect(self._on_action_button_clicked)
        print_tab_layout.addWidget(self.btn_detail_print)
        print_tab_layout.addStretch(1)

        self.return_approval_tab = None
        self.return_approval_hint = None
        self.btn_approve_return = None
        if self._is_returns_mode():
            self.return_approval_tab = QWidget(self.detail_tabs)
            approval_layout = QVBoxLayout(self.return_approval_tab)
            approval_layout.setContentsMargins(0, 0, 0, 0)
            approval_layout.setSpacing(8)
            approval_title = QLabel(orders_ui.ORDERS_DETAIL_RETURN_APPROVAL_TITLE)
            approval_title.setObjectName("CardTitle")
            approval_layout.addWidget(approval_title)
            self.return_approval_hint = QLabel(orders_ui.ORDERS_DETAIL_RETURN_APPROVAL_HINT)
            self.return_approval_hint.setObjectName("Muted")
            self.return_approval_hint.setWordWrap(True)
            approval_layout.addWidget(self.return_approval_hint)
            self.btn_approve_return = ActionPulseButton(text=orders_ui.ORDERS_DETAIL_APPROVE_RETURN_TEXT, center_text=True)
            self.btn_approve_return.setEnabled(False)
            self.btn_approve_return.clicked.connect(self._on_approve_return_clicked)
            approval_layout.addWidget(self.btn_approve_return)
            approval_layout.addStretch(1)

        self._detail_tab_index_cargo = self.detail_tabs.addTab(cargo_tab, QIcon(), str(ui_text("orders.selection_panel.detail.tab_cargo", "Kargo")))
        self._detail_tab_index_print = self.detail_tabs.addTab(print_tab, QIcon(), str(ui_text("orders.selection_panel.detail.tab_print", "Yazdır")))
        self._detail_tab_index_approval = -1
        if self.return_approval_tab is not None:
            self._detail_tab_index_approval = self.detail_tabs.addTab(self.return_approval_tab, QIcon(), "Onay")
        self.detail_tabs.setCurrentIndex(0)
        self.detail_tabs.currentChanged.connect(lambda _index=0: self._schedule_workspace_editor_refresh())
        detail_layout.addWidget(detail_bottom)
        self.selection_stack.addWidget(detail_page)

        bulk_page = QWidget(selection_card)
        bulk_layout = QVBoxLayout(bulk_page)
        bulk_layout.setContentsMargins(0, 4, 0, 0)
        bulk_layout.setSpacing(8)
        bulk_top = QWidget(bulk_page)
        bulk_top_layout = QVBoxLayout(bulk_top)
        bulk_top_layout.setContentsMargins(0, 0, 0, 0)
        bulk_top_layout.setSpacing(8)
        self.bulk_summary_label = QLabel(str(ui_text("orders.selection_panel.bulk.summary", "Seçili sipariş: {count}")).format(count=0))
        self.bulk_summary_label.setObjectName("CardTitle")
        bulk_top_layout.addWidget(self.bulk_summary_label)
        self.bulk_overview_label = QLabel(str(ui_text("orders.selection_panel.bulk.hint", "Toplu etiket/yazdırma işlemlerini buradan yönet.")))
        self.bulk_overview_label.setObjectName("Muted")
        self.bulk_overview_label.setWordWrap(True)
        bulk_top_layout.addWidget(self.bulk_overview_label)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(8)

        def _metric_card(title_text: str, initial_value: str = "0"):
            card = QFrame(bulk_page)
            card.setObjectName("Card")
            lay = QVBoxLayout(card)
            lay.setContentsMargins(10, 8, 10, 8)
            lay.setSpacing(4)
            title = QLabel(title_text)
            title.setObjectName("Muted")
            value = QLabel(initial_value)
            value.setObjectName("CardTitle")
            lay.addWidget(title)
            lay.addWidget(value)
            return card, value

        card_selected, self.bulk_metric_selected = _metric_card(str(ui_text("orders.selection_panel.bulk.metric.selected", "Seçili Sipariş")))
        card_total, self.bulk_metric_total = _metric_card(str(ui_text("orders.selection_panel.bulk.metric.total", "Toplam Tutar")), "0.00 TL")
        card_cargo, self.bulk_metric_cargo = _metric_card(str(ui_text("orders.selection_panel.bulk.metric.cargo", "Kargo Türü")))
        card_status, self.bulk_metric_status = _metric_card(str(ui_text("orders.selection_panel.bulk.metric.status", "Durum Türü")))
        metrics_row.addWidget(card_selected, 1)
        metrics_row.addWidget(card_total, 1)
        metrics_row.addWidget(card_cargo, 1)
        metrics_row.addWidget(card_status, 1)
        bulk_top_layout.addLayout(metrics_row)
        bulk_top_layout.addStretch(1)
        bulk_layout.addWidget(bulk_top)

        bulk_bottom = QWidget(bulk_page)
        bulk_bottom_layout = QVBoxLayout(bulk_bottom)
        bulk_bottom_layout.setContentsMargins(0, 0, 0, 0)
        bulk_bottom_layout.setSpacing(8)
        self.bulk_tabs = GlowTabWidget(bulk_bottom)
        self.bulk_tabs.set_tab_palette(
            container_bg="#DBEAFE",
            container_border="#93C5FD",
            indicator="#22C55E",
            text_active="#166534",
            text_inactive="#1D4ED8",
            text_hover="#0F172A",
        )
        bulk_bottom_layout.addWidget(self.bulk_tabs)

        bulk_cargo_tab = QWidget(self.bulk_tabs)
        bulk_cargo_tab_layout = QVBoxLayout(bulk_cargo_tab)
        bulk_cargo_tab_layout.setContentsMargins(0, 0, 0, 0)
        bulk_cargo_tab_layout.setSpacing(8)
        bulk_cargo_title = QLabel(str(ui_text("orders.selection_panel.bulk.cargo_change_title", "Toplu Kargo Firması Değişikliği")))
        bulk_cargo_title.setObjectName("CardTitle")
        bulk_cargo_tab_layout.addWidget(bulk_cargo_title)
        bulk_cargo_hint = QLabel(
            str(ui_text("orders.selection_panel.bulk.cargo_change_hint", "SEÇ ile işaretlenen siparişlerin kargo firmasını tek seferde güncelle."))
        )
        bulk_cargo_hint.setObjectName("Muted")
        bulk_cargo_hint.setWordWrap(True)
        bulk_cargo_tab_layout.addWidget(bulk_cargo_hint)
        bulk_cargo_row = QVBoxLayout()
        bulk_cargo_row.setSpacing(8)
        self.bulk_cargo_provider_select = SwitchSelectWidget(
            multi=False,
            include_all=False,
            empty_text=str(ui_text("orders.selection_panel.bulk.cargo_change_empty", "Kargo firması seç")),
        )
        self.bulk_cargo_provider_select.setMinimumWidth(0)
        self.bulk_cargo_provider_select.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for row in list_changeable_cargo_providers():
            code = str(row.get("code") or "").strip()
            name = str(row.get("name") or "").strip()
            if code and name:
                self.bulk_cargo_provider_select.addItem(f"{name} ({code})", data=code)
        self.btn_bulk_change_cargo_provider = QPushButton(str(ui_text("orders.selection_panel.bulk.cargo_change_button", "Toplu Kargo Güncelle")))
        self.btn_bulk_change_cargo_provider.setObjectName("Primary")
        self.btn_bulk_change_cargo_provider.setStyleSheet(
            """
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: 1px solid #2563EB;
                border-radius: 10px;
                padding: 7px 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
                border-color: #1D4ED8;
            }
            QPushButton:disabled {
                background-color: #DBEAFE;
                color: #1D4ED8;
                border: 1px solid #93C5FD;
            }
            """
        )
        self.btn_bulk_change_cargo_provider.setMinimumHeight(40)
        self.btn_bulk_change_cargo_provider.setMinimumWidth(0)
        self.btn_bulk_change_cargo_provider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_bulk_change_cargo_provider.setEnabled(False)
        self.btn_bulk_change_cargo_provider.clicked.connect(self._on_change_bulk_cargo_provider_clicked)
        bulk_cargo_row.addWidget(self.bulk_cargo_provider_select)
        bulk_cargo_row.addWidget(self.btn_bulk_change_cargo_provider)
        bulk_cargo_tab_layout.addLayout(bulk_cargo_row)
        bulk_cargo_tab_layout.addStretch(1)

        bulk_print_tab = QWidget(self.bulk_tabs)
        bulk_print_tab_layout = QVBoxLayout(bulk_print_tab)
        bulk_print_tab_layout.setContentsMargins(0, 0, 0, 0)
        bulk_print_tab_layout.setSpacing(8)
        bulk_print_title = QLabel(str(ui_text("orders.selection_panel.bulk.print_title", "Toplu Yazdırma")))
        bulk_print_title.setObjectName("CardTitle")
        bulk_print_tab_layout.addWidget(bulk_print_title)
        bulk_print_hint = QLabel(str(ui_text("orders.selection_panel.bulk.print_hint", "Seçili siparişler için etiket/yazdırma penceresini aç.")))
        bulk_print_hint.setObjectName("Muted")
        bulk_print_hint.setWordWrap(True)
        bulk_print_tab_layout.addWidget(bulk_print_hint)
        self.btn_bulk_print = ActionPulseButton(
            text=str(ui_text("orders.selection_panel.bulk.print_button", "Siparişleri Yazdır")),
            center_text=True,
        )
        self.btn_bulk_print.setEnabled(False)
        self.btn_bulk_print.clicked.connect(self._on_action_button_clicked)
        bulk_print_tab_layout.addWidget(self.btn_bulk_print)
        bulk_print_tab_layout.addStretch(1)
        self.bulk_tabs.addTab(bulk_cargo_tab, QIcon(), str(ui_text("orders.selection_panel.bulk.tab_cargo", "Kargo")))
        self.bulk_tabs.addTab(bulk_print_tab, QIcon(), str(ui_text("orders.selection_panel.bulk.tab_print", "Yazdır")))
        self.bulk_tabs.setCurrentIndex(0)
        self.bulk_tabs.currentChanged.connect(lambda _index=0: self._schedule_workspace_editor_refresh())
        bulk_layout.addWidget(bulk_bottom)
        self.selection_stack.addWidget(bulk_page)
        self.selection_stack.setCurrentIndex(0)

        self._workspace.set_editor_widget(selection_card)
        self._workspace.bulk_panel.hide()

        filters_host = QWidget(self._workspace.filters_host)
        filter_layout = QVBoxLayout(filters_host)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(4)

        self.btn_clear_filters = QPushButton(orders_ui.ORDERS_FILTER_CLEAR_BUTTON_TEXT)
        self.btn_clear_filters.setObjectName("SoftDanger")
        self.btn_clear_filters.setMinimumHeight(40)
        self.btn_clear_filters.setMinimumWidth(150)
        self.btn_clear_filters.clicked.connect(self._clear_filters_and_apply)

        def _stack(label_text: str, widget: QWidget) -> QWidget:
            wrap = QWidget()
            lay = QVBoxLayout(wrap)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(3)
            label = QLabel(label_text)
            label.setObjectName("InlineLabel")
            lay.addWidget(label)
            lay.addWidget(widget)
            return wrap

        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText(orders_ui.ORDERS_FILTER_GLOBAL_PLACEHOLDER)
        self.global_search.setObjectName("Input")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(orders_ui.ORDERS_FILTER_ORDER_NO_PLACEHOLDER)
        self.search_input.setObjectName("Input")
        self.search_input.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d*$")))
        self.cargo_filter = SwitchSelectWidget(
            title=orders_ui.ORDERS_FILTER_CARGO_TITLE,
            all_text=orders_ui.ORDERS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
        )
        self.cargo_filter.setMinimumWidth(260)
        self.platform_filter = SwitchSelectWidget(
            title=orders_ui.ORDERS_FILTER_PLATFORM_TITLE,
            all_text=orders_ui.ORDERS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
            search_enabled=True,
        )
        self.platform_filter.setMinimumWidth(220)
        self.platform_filter.setPlaceholderText(orders_ui.ORDERS_FILTER_PLATFORM_PLACEHOLDER)
        self.platform_filter.addItems(order_platform_filter_options(include_all=False))
        self.customer_input = QLineEdit()
        self.customer_input.setPlaceholderText(orders_ui.ORDERS_FILTER_CUSTOMER_PLACEHOLDER)
        self.customer_input.setObjectName("Input")
        self.processed_filter = SwitchSelectWidget(
            title=orders_ui.ORDERS_FILTER_PROCESSED_TITLE,
            all_text=orders_ui.ORDERS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
        )
        self.processed_filter.setMinimumWidth(220)
        self.processed_filter.addItem(orders_ui.ORDERS_FILTER_PROCESSED_PENDING_TEXT, data="pending")
        self.processed_filter.addItem(orders_ui.ORDERS_FILTER_PROCESSED_DONE_TEXT, data="processed")
        self.deadline_filter = SwitchSelectWidget(
            title=orders_ui.ORDERS_FILTER_DEADLINE_TITLE,
            all_text=orders_ui.ORDERS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
        )
        self.deadline_filter.setMinimumWidth(220)
        self.deadline_filter.addItem(orders_ui.ORDERS_FILTER_DEADLINE_OVERDUE_TEXT, data="overdue")
        self.deadline_filter.addItem(orders_ui.ORDERS_FILTER_DEADLINE_DUE_TODAY_TEXT, data="due_today")
        self.deadline_filter.addItem(orders_ui.ORDERS_FILTER_DEADLINE_SUFFICIENT_TEXT, data="sufficient_time")
        status_filter_title = (
            orders_ui.ORDERS_FILTER_RETURN_STATUS_TITLE
            if self._window_mode == "returns"
            else orders_ui.ORDERS_FILTER_ORDER_STATUS_TITLE
        )
        self.order_status_filter = SwitchSelectWidget(
            title=status_filter_title,
            all_text=orders_ui.ORDERS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
        )
        self.order_status_filter.setMinimumWidth(240)
        self.tracking_input = QLineEdit()
        self.tracking_input.setPlaceholderText(orders_ui.ORDERS_FILTER_TRACKING_PLACEHOLDER)
        self.tracking_input.setObjectName("Input")
        self.amount_min_input = QLineEdit()
        self.amount_min_input.setPlaceholderText(orders_ui.ORDERS_FILTER_AMOUNT_MIN_PLACEHOLDER)
        self.amount_min_input.setObjectName("Input")
        min_validator = QDoubleValidator(0.0, 999999999.0, 2, self.amount_min_input)
        min_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.amount_min_input.setValidator(min_validator)
        self.amount_max_input = QLineEdit()
        self.amount_max_input.setPlaceholderText(orders_ui.ORDERS_FILTER_AMOUNT_MAX_PLACEHOLDER)
        self.amount_max_input.setObjectName("Input")
        max_validator = QDoubleValidator(0.0, 999999999.0, 2, self.amount_max_input)
        max_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.amount_max_input.setValidator(max_validator)
        self.search_input.setVisible(False)
        self.customer_input.setVisible(False)
        self.tracking_input.setVisible(False)
        self.amount_min_input.setVisible(False)
        self.amount_max_input.setVisible(False)

        self.date_range = DateSelector(range_enabled=True)
        self._apply_default_filter_date_range()
        self.date_range.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.date_range.setMaximumWidth(360)

        row0 = QHBoxLayout()
        row0.setContentsMargins(0, 0, 0, 0)
        row0.setSpacing(10)
        row0.addWidget(_stack("Genel", self.global_search), 1)
        row0.addWidget(self.btn_clear_filters, 0, Qt.AlignmentFlag.AlignBottom)
        filter_layout.addLayout(row0)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(_stack("İşlenme", self.processed_filter), 1)
        row1.addWidget(_stack(status_filter_title, self.order_status_filter), 1)
        row1.addWidget(_stack("Kargo", self.cargo_filter), 1)
        filter_layout.addLayout(row1)

        date_stack = _stack("Tarih", self.date_range)
        date_stack.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        date_stack.setMaximumWidth(400)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(date_stack)
        if not self._is_returns_mode():
            row2.addWidget(_stack("Kargolama", self.deadline_filter))
        row2.addWidget(_stack("Platform", self.platform_filter))
        row2.addStretch(1)
        filter_layout.addLayout(row2)

        self.lbl_filter_info = QLabel(orders_ui.ORDERS_FILTER_SUMMARY_EMPTY_TEXT)
        self.lbl_filter_info.setObjectName("Muted")
        filter_layout.addWidget(self.lbl_filter_info)
        self._workspace.set_filters_widget(filters_host)

        self._workspace.set_list_widget(self.list_widget)
        self.list_widget.set_loading_overlay_hooks(
            set_busy=self._workspace.set_list_loading,
            sync_geometry=self._workspace.sync_list_loading_geometry,
        )
        self._orders_list_card = self._workspace.records_card
        self.selected_count_label = QLabel("")
        self.selected_count_label.setVisible(False)

        self._workspace.footer_bar.setObjectName("BottomBar")
        self.btn_bulk_select_toggle = self._workspace.footer_bar.select_toggle
        try:
            self.btn_bulk_select_toggle.actionRequested.disconnect(self._workspace.footer_bar._on_toggle_requested)
        except Exception:
            pass
        self.btn_bulk_select_toggle.actionRequested.connect(self._on_bulk_toggle_action)
        self.prev_page_btn = self._workspace.footer_bar.prev_button
        self.next_page_btn = self._workspace.footer_bar.next_button
        self.pagination_label = self._workspace.footer_bar.page_label
        self.pagination_label.setObjectName("PaginationStrong")
        self.pagination_label.setTextFormat(Qt.TextFormat.RichText)
        self.page_size_box = self._workspace.footer_bar.page_size_combo
        self.page_size_box.setObjectName("Combo")
        self.prev_page_btn.setObjectName("NavBtn")
        self.next_page_btn.setObjectName("NavBtn")
        self._workspace.footer_bar.page_size_label.setText(orders_ui.ORDERS_FILTER_PAGE_SIZE_TEXT)

        self._orders_splitter.setSizes([0, 1280])
        self._workspace_shell.set_left_guidance_targets(
            host=self._workspace.left_card,
            editor_widget=selection_card,
            bulk_widget=selection_card,
        )
        self._workspace_shell.set_right_guidance_widget(self.list_widget, host=self._workspace.right_card)

        self.list_widget.data_loaded.connect(self._refresh_cargo_filter)
        self.list_widget.data_loaded.connect(self._refresh_order_status_filter)
        self.list_widget.data_loaded.connect(self._update_label)
        self.list_widget.data_loaded.connect(self._on_orders_loaded_update_pagination)
        self.list_widget.data_loaded.connect(self._on_orders_loaded_trigger_debounce)
        self.platform_filter.selectionChanged.connect(lambda _v: self._refresh_cargo_filter())

        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.apply_filters)
        inputs = [
            self.global_search,
            self.search_input,
            self.customer_input,
            self.cargo_filter,
            self.platform_filter,
            self.order_status_filter,
            self.deadline_filter,
            self.tracking_input,
            self.amount_min_input,
            self.amount_max_input,
            self.date_range,
            self.processed_filter,
        ]
        for w in inputs:
            if isinstance(w, SwitchSelectWidget):
                w.selectionChanged.connect(lambda _v: self._trigger_debounce())
            elif isinstance(w, DateSelector):
                w.rangeChanged.connect(lambda _f, _t: self._trigger_debounce())
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._trigger_debounce)
            elif hasattr(w, "textChanged"):
                w.textChanged.connect(self._trigger_debounce)
            elif hasattr(w, "dateChanged"):
                w.dateChanged.connect(self._trigger_debounce)

        self.date_range.rangeChanged.connect(self._on_date_range_user_changed)
        self._apply_default_order_status_selection()
        if self._window_mode == "returns":
            self._returns_remote_signature = self._current_returns_remote_signature()
        self._configure_mode_specific_ui()
        self._refresh_detail_cargo_provider_options()
        self._refresh_bulk_cargo_provider_options()
        self._workspace_adapter = OrdersWorkspaceBehaviorAdapter(self)
        self._workspace_behavior = self._workspace.create_behavior_controller(
            adapter=self._workspace_adapter,
        )
        self._refresh_selection_side_panel()
        self._schedule_workspace_editor_refresh()

    @staticmethod
    def _default_filter_date_range() -> tuple[QDate, QDate]:
        today = QDate.currentDate()
        return today.addDays(-30), today.addDays(1)

    def _is_returns_mode(self) -> bool:
        return self._window_mode == "returns"

    def _current_returns_remote_signature(self) -> tuple[str, str]:
        return (
            str(self.date_range.dateFrom().toString("yyyy-MM-dd")),
            str(self.date_range.dateTo().toString("yyyy-MM-dd")),
        )

    def _current_orders_source_signature(self) -> tuple[str, str, str, str]:
        raw_status = self._filter_current_value(self.order_status_filter)
        raw_platform = self._filter_current_value(self.platform_filter)
        return (
            raw_status.casefold(),
            raw_platform.casefold(),
            str(self.date_range.dateFrom().toString("yyyy-MM-dd")),
            str(self.date_range.dateTo().toString("yyyy-MM-dd")),
        )

    @staticmethod
    def _filter_current_value(widget) -> str:
        try:
            data = widget.currentData()
        except Exception:
            data = None
        data_text = str(data).strip() if data is not None else ""
        if data_text:
            return data_text
        try:
            text = widget.currentText()
        except Exception:
            text = ""
        return str(text or "").strip()

    def _load_records_for_window(self) -> Result:
        if not self._is_returns_mode():
            self._orders_source_signature = self._current_orders_source_signature()
            return load_orders_for_source_filters(
                shipment_status_code=self._filter_current_value(self.order_status_filter),
                platform_code=self._filter_current_value(self.platform_filter),
                date_from=self.date_range.dateFrom().toPyDate(),
                date_to=self.date_range.dateTo().toPyDate(),
            )
        return load_returns_for_source_filters(
            shipment_status_code=self._filter_current_value(self.order_status_filter),
            platform_code=self._filter_current_value(self.platform_filter),
            date_from=self.date_range.dateFrom().toPyDate(),
            date_to=self.date_range.dateTo().toPyDate(),
        )

    def _configure_mode_specific_ui(self) -> None:
        if not self._is_returns_mode():
            return

        self.selection_title.setText(orders_ui.ORDERS_RETURN_DETAIL_TITLE)
        self.detail_order_no_label.setText(orders_ui.ORDERS_RETURN_NO_LABEL)
        self.detail_status_label.setText(orders_ui.ORDERS_RETURN_STATUS_LABEL)

        self.btn_change_cargo_provider.setEnabled(False)
        self.btn_change_cargo_provider.setToolTip(orders_ui.ORDERS_RETURNS_CARGO_CHANGE_UNSUPPORTED_TOOLTIP)
        self.detail_cargo_provider_select.setEnabled(False)
        self.btn_bulk_change_cargo_provider.setEnabled(False)
        self.btn_bulk_change_cargo_provider.setToolTip(
            orders_ui.ORDERS_RETURNS_BULK_CARGO_CHANGE_UNSUPPORTED_TOOLTIP
        )
        self.bulk_cargo_provider_select.setEnabled(False)

        self.btn_detail_print.setEnabled(False)
        self.btn_detail_print.setToolTip(orders_ui.ORDERS_RETURNS_PRINT_UNSUPPORTED_TOOLTIP)
        self.btn_bulk_print.setEnabled(False)
        self.btn_bulk_print.setToolTip(orders_ui.ORDERS_RETURNS_BULK_PRINT_UNSUPPORTED_TOOLTIP)
        if self.btn_approve_return is not None:
            self.btn_approve_return.setEnabled(False)
            self.btn_approve_return.setToolTip(orders_ui.ORDERS_RETURNS_APPROVAL_UNSUPPORTED_TOOLTIP)

    def _apply_default_filter_date_range(self) -> None:
        date_from, date_to = self._default_filter_date_range()
        self.date_range.setRange(date_from, date_to)
        self._date_range_user_overridden = False

    def _sync_default_filter_date_range_if_unmodified(self) -> None:
        if self._date_range_user_overridden:
            return
        expected_from, expected_to = self._default_filter_date_range()
        current_from = self.date_range.dateFrom()
        current_to = self.date_range.dateTo()
        if current_from == expected_from and current_to == expected_to:
            return
        self.date_range.setSignalsBlocked(True)
        try:
            self.date_range.setRange(expected_from, expected_to)
        finally:
            self.date_range.setSignalsBlocked(False)

    def _on_date_range_user_changed(self, _date_from: QDate, _date_to: QDate) -> None:
        self._date_range_user_overridden = True

    def _apply_default_order_status_selection(self) -> None:
        """
        Açılış varsayılanı: Sipariş Durumu = Created (Kargoya Hazır).
        Bu seçim pencere görünmeden önce yapılır ki "önce tümü sonra kargoya hazır"
        hissi oluşmasın.
        """
        if self._is_returns_mode():
            with _signals_blocked(self.order_status_filter):
                target_idx = -1
                try:
                    target_idx = int(self.order_status_filter.findData("WaitingInAction"))
                except Exception:
                    target_idx = -1
                if target_idx < 0:
                    try:
                        target_idx = int(self.order_status_filter.findText("Aksiyon Bekliyor"))
                    except Exception:
                        target_idx = -1
                if target_idx >= 0:
                    self.order_status_filter.setCurrentIndex(target_idx)
                else:
                    self.order_status_filter.setCurrentText("Aksiyon Bekliyor")
            return

        has_ready_to_ship = False
        try:
            source_orders = list(self.list_widget.orders or [])
            for order in source_orders:
                status_code = str(
                    getattr(order, "shipmentPackageStatus", None)
                    or getattr(order, "status", "")
                    or ""
                ).strip()
                if status_code.casefold() in ("created", "readytoship"):
                    has_ready_to_ship = True
                    break
        except Exception:
            has_ready_to_ship = False

        with _signals_blocked(self.order_status_filter):
            if not has_ready_to_ship:
                self.order_status_filter.setCurrentText("Tümü")
                return

            target_idx = -1
            try:
                target_idx = int(self.order_status_filter.findData("Created"))
            except Exception:
                target_idx = -1

            if target_idx < 0:
                try:
                    target_idx = int(self.order_status_filter.findData("ReadyToShip"))
                except Exception:
                    target_idx = -1

            if target_idx < 0:
                try:
                    target_idx = int(self.order_status_filter.findText("Kargoya Hazır"))
                except Exception:
                    target_idx = -1

            if target_idx >= 0:
                self.order_status_filter.setCurrentIndex(target_idx)
            else:
                self.order_status_filter.setCurrentText("Tümü")

    def prepare_open_filters(self) -> None:
        """
        Pencere her açılışında varsayılan filtreleri ilk render öncesi uygular.
        """
        self._sync_default_filter_date_range_if_unmodified()
        self._apply_default_order_status_selection()
        self._last_applied_filter_signature = None
        if self._is_returns_mode():
            self._returns_remote_signature = self._current_returns_remote_signature()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.list_widget.sync_dynamic_row_width()
        self._sync_bulk_guidance_overlays_geometry()
        self._sync_bulk_guidance_state()
        self._update_selection_lock_state()

    def showEvent(self, event):
        super().showEvent(event)
        if self._closing:
            self._closing = False
            self.list_widget.resume_workers()

    @staticmethod
    def _request_worker_stop(worker: SyncWorker | None, wait_ms: int = 1500) -> None:
        if worker is None:
            return
        try:
            worker.requestInterruption()
        except Exception:
            pass
        try:
            if worker.isRunning():
                worker.wait(max(0, int(wait_ms)))
        except Exception:
            pass

    def closeEvent(self, event):
        self._closing = True
        self._filter_request_seq += 1
        self._order_profit_request_seq += 1
        self.filter_timer.stop()
        self.list_widget.shutdown_workers()
        workers = [
            self.reload_worker,
            self.filter_worker,
            self._order_profit_worker,
            self._cargo_change_worker,
            self._bulk_cargo_change_worker,
            *self._filter_workers,
            *self._profit_workers,
        ]
        seen: set[int] = set()
        for worker in workers:
            if worker is None or id(worker) in seen:
                continue
            seen.add(id(worker))
            self._request_worker_stop(worker)
        super().closeEvent(event)

    def _on_orders_loaded_update_pagination(self, _orders=None):
        self._update_pagination_ui()

    def _on_orders_loaded_trigger_debounce(self, _orders=None):
        self._trigger_debounce()

    def _is_selection_panel_open(self) -> bool:
        sizes = self._orders_splitter.sizes()
        if len(sizes) < 2:
            return False
        return int(sizes[0]) > 8

    def _sync_bulk_guidance_overlays_geometry(self):
        self._workspace.sync_list_loading_geometry()
        self._workspace_shell.sync_guidance_geometry()

    def _sync_bulk_guidance_state(self):
        panel_open = self._is_selection_panel_open()
        detail_mode = self._selection_mode == "detail" and panel_open
        bulk_mode = self._selection_mode == "bulk" and panel_open
        selected_count = len(self.list_widget.get_selected_orders() or [])
        detail_needs_guidance = detail_mode and self._active_order is None
        bulk_needs_guidance = bulk_mode and selected_count <= 0

        self.list_widget.set_select_button_guide_enabled(bulk_needs_guidance)
        self._workspace_shell.set_right_guidance_enabled(detail_needs_guidance)

    def _update_selection_lock_state(self):
        panel_open = self._is_selection_panel_open()
        selected_count = len(self.list_widget.get_selected_orders() or [])
        lock_detail = panel_open and self._selection_mode == "detail" and self._active_order is None
        lock_bulk = panel_open and self._selection_mode == "bulk" and selected_count <= 0
        self._workspace_shell.set_left_highlight_enabled(lock_detail or lock_bulk)
        self._workspace_shell.sync_guidance_geometry()

    def _sync_active_card_spin_state(self):
        allow_spin = (
            self._selection_mode == "detail"
            and self._is_selection_panel_open()
            and self._active_order is not None
        )
        self.list_widget.set_active_spin_allowed(bool(allow_spin))

    def _sync_workspace_behavior_state(self):
        state_signature = (
            str(self._selection_mode or ""),
            bool(self._workspace_shell.is_left_panel_open()),
            self._workspace_record_key(self._active_order),
            len(self.list_widget.get_selected_orders() or []),
        )
        if state_signature == self._last_workspace_state_signature:
            return
        self._last_workspace_state_signature = state_signature
        self._refresh_selection_side_panel()
        self._sync_active_card_spin_state()

    def _sync_detail_cargo_provider_selection(self, current_name_or_code: str):
        code = cargo_provider_code_for_name(
            current_name_or_code,
            platform_code=self._order_platform_code(self._active_order),
        )
        if not code:
            return
        idx = self.detail_cargo_provider_select.findData(code)
        if idx >= 0:
            self.detail_cargo_provider_select.setCurrentIndex(idx)

    def _on_change_cargo_provider_clicked(self):
        if self._is_returns_mode():
            MessageHandler.show(
                self,
                Result.fail("İade kayıtlarında kargo firması güncelleme desteklenmiyor.", close_dialog=False),
                only_errors=True,
            )
            return
        if self._active_order is None:
            MessageHandler.show(
                self,
                Result.fail("Önce bir sipariş kartına tıklayıp detay açmalısın.", close_dialog=False),
                only_errors=True,
            )
            return
        provider_code = str(self.detail_cargo_provider_select.currentData() or "").strip().upper()
        if not provider_code:
            MessageHandler.show(
                self,
                Result.fail("Önce bir kargo firması seçmelisin.", close_dialog=False),
                only_errors=True,
            )
            return

        self.btn_change_cargo_provider.setEnabled(False)
        self._cargo_change_worker = SyncWorker(
            change_order_cargo_provider,
            order=self._active_order,
            cargo_provider_code=provider_code,
            parent=self,
        )
        self._cargo_change_worker.result_ready.connect(self._on_change_cargo_provider_result)
        self._cargo_change_worker.finished.connect(
            lambda: self.btn_change_cargo_provider.setEnabled(self._active_order is not None)
        )
        self._cargo_change_worker.start()

    def _on_change_cargo_provider_result(self, result: Result):
        MessageHandler.show(self, result, only_errors=False)
        if not result.success:
            return
        if self._active_order is not None:
            try:
                provider_name = str((result.data or {}).get("cargo_provider_name") or "").strip()
                provider_code = str((result.data or {}).get("cargo_provider_code") or "").strip()
                if provider_name:
                    setattr(self._active_order, "cargoProviderName", provider_name)
                    self.detail_cargo.setText(provider_name)
                if provider_code:
                    self._sync_detail_cargo_provider_selection(provider_code)
            except Exception:
                pass
        self.list_widget._safe_build(self.list_widget.filtered_orders)
        self._update_label()
        self._refresh_selection_side_panel()

    def _on_change_bulk_cargo_provider_clicked(self):
        if self._is_returns_mode():
            MessageHandler.show(
                self,
                Result.fail("İade kayıtlarında toplu kargo güncelleme desteklenmiyor.", close_dialog=False),
                only_errors=True,
            )
            return
        selected_orders = self.list_widget.get_selected_orders() or []
        if not selected_orders:
            MessageHandler.show(
                self,
                Result.fail("Toplu güncelleme için en az bir siparişi SEÇ ile işaretlemelisin.", close_dialog=False),
                only_errors=True,
            )
            return

        provider_code = str(self.bulk_cargo_provider_select.currentData() or "").strip().upper()
        if not provider_code:
            MessageHandler.show(
                self,
                Result.fail("Önce bir kargo firması seçmelisin.", close_dialog=False),
                only_errors=True,
            )
            return

        self.btn_bulk_change_cargo_provider.setEnabled(False)
        self._bulk_cargo_change_worker = SyncWorker(
            change_orders_cargo_provider_bulk,
            orders=selected_orders,
            cargo_provider_code=provider_code,
            parent=self,
        )
        self._bulk_cargo_change_worker.result_ready.connect(self._on_change_bulk_cargo_provider_result)
        self._bulk_cargo_change_worker.finished.connect(
            lambda: self.btn_bulk_change_cargo_provider.setEnabled(
                len(self.list_widget.get_selected_orders() or []) > 0
            )
        )
        self._bulk_cargo_change_worker.start()

    def _on_change_bulk_cargo_provider_result(self, result: Result):
        MessageHandler.show(self, result, only_errors=False)
        data = (result.data or {}) if isinstance(result.data, dict) else {}
        provider_name = str(data.get("cargo_provider_name") or "").strip()
        if provider_name:
            for order in (self.list_widget.get_selected_orders() or []):
                try:
                    setattr(order, "cargoProviderName", provider_name)
                except Exception:
                    pass
            if self._active_order is not None:
                try:
                    setattr(self._active_order, "cargoProviderName", provider_name)
                    self.detail_cargo.setText(provider_name)
                except Exception:
                    pass
        self.list_widget._safe_build(self.list_widget.filtered_orders)
        self._update_label()
        self._refresh_selection_side_panel()

    @staticmethod
    def _format_order_date(order) -> str:
        val = getattr(order, "orderDate", None)
        if isinstance(val, datetime):
            return val.strftime("%d.%m.%Y %H:%M")
        if isinstance(val, (int, float)):
            try:
                ts = float(val)
                if ts > 10_000_000_000:
                    ts = ts / 1000.0
                return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
            except Exception:
                return str(val)
        return str(val or "-")

    @staticmethod
    def _format_money(amount) -> str:
        try:
            return f"{float(amount):,.2f}".replace(",", ".") + " TL"
        except Exception:
            return str(amount or "-")

    @staticmethod
    def _format_item_amount(amount) -> str:
        try:
            return f"{float(amount):,.2f} TL".replace(",", ".")
        except Exception:
            return "-"

    @staticmethod
    def _first_non_empty(*values, default: str = "") -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return str(default or "")

    @staticmethod
    def _coerce_dict(value) -> dict:
        return value if isinstance(value, dict) else {}

    def _extract_order_contact_and_address(self, order) -> tuple[str, str]:
        return extract_contact_and_address(
            getattr(order, "shipmentAddress", None),
            getattr(order, "invoiceAddress", None),
        )

    def _detail_cache_key_for_order(self, order) -> str:
        if order is None:
            return ""
        if bool(getattr(order, "_is_return", False)):
            claim_key = str(
                getattr(order, "claimId", "")
                or getattr(order, "claimNumber", "")
                or getattr(order, "id", "")
            ).strip()
            if claim_key:
                return f"return:{claim_key}"
        order_number = str(getattr(order, "orderNumber", "") or "").strip()
        api_account_id = getattr(order, "api_account_id", None)
        if order_number and api_account_id is not None:
            return f"order:{api_account_id}:{order_number}"
        return order_number

    def _cache_order_items(self, cache_key: str, items: list[dict]) -> None:
        if not cache_key:
            return
        self._order_items_cache[cache_key] = items
        self._order_items_cache.move_to_end(cache_key)
        while len(self._order_items_cache) > ORDER_ITEMS_CACHE_LIMIT:
            self._order_items_cache.popitem(last=False)

    def _load_order_items(self, order) -> list[dict]:
        cache_key = self._detail_cache_key_for_order(order)
        if not cache_key:
            return []
        cached = self._order_items_cache.get(cache_key)
        if cached is not None:
            self._order_items_cache.move_to_end(cache_key)
            return cached

        if bool(getattr(order, "_is_return", False)):
            return_items = getattr(order, "_return_items", None)
            if isinstance(return_items, list):
                self._cache_order_items(cache_key, return_items)
                return return_items
            self._cache_order_items(cache_key, [])
            return []

        order_no = str(getattr(order, "orderNumber", "") or "").strip()
        if not order_no:
            return []

        res = load_order_items_for_order_number(order_no, api_account_id=getattr(order, "api_account_id", None))
        if not res.success:
            MessageHandler.show(self, res, only_errors=True)
            self._cache_order_items(cache_key, [])
            return []
        items = (res.data or {}).get("items", []) or []
        if not isinstance(items, list):
            items = []
        self._cache_order_items(cache_key, items)
        return items

    def _ensure_order_profit_catalog(self, orders: list | None = None) -> bool:
        if self._is_returns_mode():
            return False
        requested_account_ids: set[int] = set()
        for order in (orders or []):
            try:
                account_id = int(getattr(order, "api_account_id", None) or 0)
            except Exception:
                account_id = 0
            if account_id > 0:
                requested_account_ids.add(account_id)

        if self._order_profit_catalog and requested_account_ids.issubset(self._order_profit_catalog_account_ids):
            return True

        res = load_order_profit_catalog(api_account_ids=sorted(requested_account_ids))
        if not res.success:
            self._order_profit_catalog = None
            self._order_profit_catalog_account_ids = set()
            return False

        self._order_profit_catalog = dict(res.data or {})
        self._order_profit_catalog_account_ids = set(requested_account_ids)
        return True

    @staticmethod
    def _order_item_batch_key_for_order(order) -> tuple[int | None, str]:
        try:
            account_id = int(getattr(order, "api_account_id", None))
        except Exception:
            account_id = None
        return account_id, str(getattr(order, "orderNumber", "") or "").strip()

    def _requested_profit_account_ids(self, orders: list) -> set[int]:
        requested_account_ids: set[int] = set()
        for order in orders or []:
            try:
                account_id = int(getattr(order, "api_account_id", None) or 0)
            except Exception:
                account_id = 0
            if account_id > 0:
                requested_account_ids.add(account_id)
        return requested_account_ids

    def _load_profit_inputs_for_orders(self, orders: list) -> Result:
        orders = [order for order in list(orders or []) if order is not None]
        requested_account_ids = self._requested_profit_account_ids(orders)

        if self._order_profit_catalog and requested_account_ids.issubset(self._order_profit_catalog_account_ids):
            catalog = self._order_profit_catalog
            catalog_account_ids = set(self._order_profit_catalog_account_ids)
        else:
            catalog_res = load_order_profit_catalog(api_account_ids=sorted(requested_account_ids))
            if not catalog_res.success:
                return catalog_res
            catalog = dict(catalog_res.data or {})
            catalog_account_ids = set(requested_account_ids)

        missing_orders = [
            order
            for order in orders
            if self._detail_cache_key_for_order(order) not in self._order_items_cache
        ]
        batch_items_by_key: dict[tuple[int | None, str], list[dict]] = {}
        if missing_orders:
            order_numbers = [
                str(getattr(order, "orderNumber", "") or "").strip()
                for order in missing_orders
                if str(getattr(order, "orderNumber", "") or "").strip()
            ]
            account_ids = [
                account_id
                for account_id, _order_no in (self._order_item_batch_key_for_order(order) for order in missing_orders)
                if account_id is not None
            ]
            if order_numbers:
                items_res = load_order_items_for_order_numbers(
                    order_numbers,
                    api_account_ids=account_ids or None,
                )
                if not items_res.success:
                    return items_res
                batch_items_by_key = dict((items_res.data or {}).get("items_by_order", {}) or {})

        items_by_cache_key: dict[str, list[dict]] = {}
        payloads_by_cache_key: dict[str, dict] = {}
        for order in orders:
            cache_key = self._detail_cache_key_for_order(order)
            if not cache_key:
                continue

            items = self._order_items_cache.get(cache_key)
            if items is None:
                if bool(getattr(order, "_is_return", False)):
                    return_items = getattr(order, "_return_items", None)
                    items = list(return_items or []) if isinstance(return_items, list) else []
                else:
                    items = list(batch_items_by_key.get(self._order_item_batch_key_for_order(order), []) or [])
            else:
                items = list(items or [])

            items_by_cache_key[cache_key] = items
            payloads_by_cache_key[cache_key] = estimate_order_profit(
                order=order,
                order_items=items,
                catalog=catalog,
            )

        return Result.ok(
            "Sipariş kar payloadları hazırlandı.",
            close_dialog=False,
            data={
                "catalog": catalog,
                "catalog_account_ids": sorted(catalog_account_ids),
                "items_by_cache_key": items_by_cache_key,
                "payloads_by_cache_key": payloads_by_cache_key,
            },
        )

    def _apply_profit_payload_to_order(self, order, payload: dict) -> None:
        payload = dict(payload or {})
        setattr(order, "_estimated_profit_payload", payload)
        setattr(order, "_estimated_profit_text", _safe_str(payload.get("estimated_profit_text")) or "-")
        setattr(order, "_estimated_profit_ready", bool(payload.get("estimated_profit_ready")))
        setattr(order, "_estimated_profit_value", payload.get("estimated_profit"))

    def _queue_profit_decoration(self, orders: list, *, open_detail_order=None) -> None:
        if self._closing or self._is_returns_mode():
            return
        raw_orders = [order for order in list(orders or []) if order is not None]
        orders = []
        seen_keys: set[str] = set()
        for order in raw_orders:
            cache_key = self._detail_cache_key_for_order(order)
            if not cache_key or cache_key in seen_keys or cache_key in self._profit_pending_keys:
                continue
            seen_keys.add(cache_key)
            orders.append(order)
        if not orders:
            if open_detail_order is not None:
                self._pending_profit_detail_key = self._detail_cache_key_for_order(open_detail_order)
            return

        for order in orders:
            if not isinstance(getattr(order, "_estimated_profit_payload", None), dict):
                setattr(order, "_estimated_profit_text", "Hesaplanıyor...")
                setattr(order, "_estimated_profit_ready", False)

        if open_detail_order is not None:
            self._pending_profit_detail_key = self._detail_cache_key_for_order(open_detail_order)

        self._order_profit_request_seq += 1
        keys_to_orders = {
            self._detail_cache_key_for_order(order): order
            for order in orders
            if self._detail_cache_key_for_order(order)
        }
        self._profit_pending_keys.update(keys_to_orders.keys())

        worker = SyncWorker(self._load_profit_inputs_for_orders, orders)
        self._order_profit_worker = worker
        self._profit_workers.append(worker)

        def _handle_result(result: Result) -> None:
            if self._closing:
                return
            if not result.success:
                for order in keys_to_orders.values():
                    payload = {
                        "estimated_profit": None,
                        "estimated_profit_text": "-",
                        "estimated_profit_ready": False,
                        "estimated_profit_detail": {
                            "summary": {"order_number": _safe_str(getattr(order, "orderNumber", ""))},
                            "results": {},
                            "lines": [],
                        },
                        "estimated_profit_missing_reasons": [str(result.message or "Kar hesabi hazirlanamadi.")],
                    }
                    self._apply_profit_payload_to_order(order, payload)
                self.list_widget._safe_build(self.list_widget.filtered_orders)
                return
            data = result.data or {}
            catalog = data.get("catalog")
            if isinstance(catalog, dict):
                self._order_profit_catalog = catalog
                self._order_profit_catalog_account_ids = {
                    int(value)
                    for value in (data.get("catalog_account_ids") or [])
                    if value is not None
                }
            for cache_key, items in (data.get("items_by_cache_key") or {}).items():
                if isinstance(items, list):
                    self._cache_order_items(str(cache_key), items)
            for cache_key, payload in (data.get("payloads_by_cache_key") or {}).items():
                order = keys_to_orders.get(str(cache_key))
                if order is None or not isinstance(payload, dict):
                    continue
                self._apply_profit_payload_to_order(order, payload)

            self.list_widget._safe_build(self.list_widget.filtered_orders)
            pending_key = str(self._pending_profit_detail_key or "")
            if pending_key and pending_key in keys_to_orders:
                self._pending_profit_detail_key = ""
                self._open_order_profit_detail(keys_to_orders[pending_key])

        def _cleanup() -> None:
            for cache_key in keys_to_orders:
                self._profit_pending_keys.discard(cache_key)
            try:
                self._profit_workers.remove(worker)
            except ValueError:
                pass
            if self._order_profit_worker is worker:
                self._order_profit_worker = None
            worker.deleteLater()

        worker.result_ready.connect(_handle_result)
        worker.finished.connect(_cleanup)
        worker.start()

    def _decorate_orders_with_profit(self, orders: list) -> None:
        if self._is_returns_mode():
            return
        orders = list(orders or [])
        if not orders:
            return
        missing = [
            order
            for order in orders
            if not isinstance(getattr(order, "_estimated_profit_payload", None), dict)
        ]
        if missing:
            self._queue_profit_decoration(missing)

    def _prewarm_order_profit_window(self) -> None:
        if self._closing or self._is_returns_mode() or self._order_profit_window is not None:
            return
        try:
            self._order_profit_window = OrderProfitBreakdownWindow(self)
        except Exception:
            self._order_profit_window = None

    def _open_order_profit_detail(self, order) -> None:
        if order is None or self._is_returns_mode():
            return
        payload = getattr(order, "_estimated_profit_payload", None)
        if not isinstance(payload, dict):
            self._queue_profit_decoration([order], open_detail_order=order)
            return
        if self._order_profit_window is None:
            self._order_profit_window = OrderProfitBreakdownWindow(self)
        self._order_profit_window.set_order_payload(order=order, payload=payload)
        self._order_profit_window.showMaximized()
        self._order_profit_window.raise_()
        self._order_profit_window.activateWindow()

    def _fill_detail_items_table(self, order):
        rows = self._load_order_items(order)
        table = self.detail_items_table
        if not rows:
            empty_text_default = (
                "Bu iade için ürün satırı bulunamadı."
                if self._is_returns_mode()
                else "Bu sipariş için ürün satırı bulunamadı."
            )
            empty_text = (
                empty_text_default
                if self._is_returns_mode()
                else str(ui_text("orders.selection_panel.detail.items_empty", empty_text_default))
            )
            self.detail_items_hint.setText(empty_text)
            self.detail_items_hint.show()
            table.setRowCount(0)
            return

        self.detail_items_hint.hide()
        with optimized_table_updates(table, len(rows)):
            for row_idx, item in enumerate(rows):
                product = str(item.get("name") or "-")
                sku = str(item.get("sku") or "-")
                barcode = str(item.get("barcode") or "-")
                qty = str(item.get("qty") if item.get("qty") is not None else "-")
                display_amount = item.get("unit_price")
                if display_amount in (None, ""):
                    display_amount = item.get("amount")
                amount = self._format_item_amount(display_amount)
                values = [product, sku, barcode, qty, amount]
                for col_idx, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(row_idx, col_idx, cell)

    def _refresh_bulk_overview(self, selected_orders: list) -> None:
        orders = list(selected_orders or [])
        count = len(orders)

        summary_default = "Seçili iade: {count}" if self._is_returns_mode() else "Seçili sipariş: {count}"
        summary_template = (
            summary_default
            if self._is_returns_mode()
            else str(ui_text("orders.selection_panel.bulk.summary", summary_default))
        )
        try:
            summary_text = summary_template.format(count=count)
        except Exception:
            summary_prefix = "Seçili iade" if self._is_returns_mode() else "Seçili sipariş"
            summary_text = f"{summary_prefix}: {count}"
        self.bulk_summary_label.setText(summary_text)

        total_amount = 0.0
        cargo_names: set[str] = set()
        status_names: set[str] = set()
        for order in orders:
            try:
                total_amount += float(getattr(order, "totalPrice", 0) or 0)
            except Exception:
                pass
            cargo_text = str(getattr(order, "cargoProviderName", "") or "").strip()
            if cargo_text:
                cargo_names.add(cargo_text)
            status_code = str(getattr(order, "shipmentPackageStatus", None) or getattr(order, "status", "") or "").strip()
            if status_code:
                status_names.add(format_order_status(status_code))

        overview_text = (
            f"Toplam tutar: {self._format_money(total_amount)} | "
            f"Kargo firması: {len(cargo_names)} | "
            f"Durum Türü: {len(status_names)}"
        )
        self.bulk_overview_label.setText(overview_text)
        if self.bulk_metric_selected is not None:
            self.bulk_metric_selected.setText(str(count))
        if self.bulk_metric_total is not None:
            self.bulk_metric_total.setText(self._format_money(total_amount))
        if self.bulk_metric_cargo is not None:
            self.bulk_metric_cargo.setText(str(len(cargo_names)))
        if self.bulk_metric_status is not None:
            self.bulk_metric_status.setText(str(len(status_names)))

    @staticmethod
    def _normalize_detail_action_status(order) -> str:
        raw_status = str(
            getattr(order, "shipmentPackageStatus", None) or getattr(order, "status", "") or ""
        ).strip()
        if not raw_status:
            return ""
        normalized = raw_status.casefold()
        if normalized == "readytoship":
            return "created"
        return normalized

    def _can_change_cargo_for_order(self, order) -> bool:
        if order is None or self._is_returns_mode():
            return False
        return self._normalize_detail_action_status(order) == "created"

    def _can_print_order(self, order) -> bool:
        if order is None or self._is_returns_mode():
            return False
        return self._normalize_detail_action_status(order) in {"created", "shipped"}

    def _set_detail_tab_visible(self, index: int, visible: bool) -> None:
        if index < 0 or self.detail_tabs is None:
            return
        try:
            self.detail_tabs.setTabVisible(index, bool(visible))
        except Exception:
            try:
                self.detail_tabs.tabBar().setTabVisible(index, bool(visible))
            except Exception:
                pass

    def _sync_detail_tab_visibility(self, order) -> None:
        if self.detail_tabs is None:
            return

        if self._is_returns_mode():
            allow_cargo = False
            allow_print = False
            allow_approval = self._detail_tab_index_approval >= 0
        else:
            allow_cargo = self._can_change_cargo_for_order(order)
            allow_print = self._can_print_order(order)
            allow_approval = False

        self._set_detail_tab_visible(self._detail_tab_index_cargo, allow_cargo)
        self._set_detail_tab_visible(self._detail_tab_index_print, allow_print)
        self._set_detail_tab_visible(self._detail_tab_index_approval, allow_approval)

        visible_indexes = [
            idx for idx, allowed in (
                (self._detail_tab_index_cargo, allow_cargo),
                (self._detail_tab_index_print, allow_print),
                (self._detail_tab_index_approval, allow_approval),
            )
            if idx >= 0 and allowed
        ]

        has_visible_tabs = bool(visible_indexes)
        self.detail_tabs.setVisible(has_visible_tabs)
        if self.detail_tab_hint is not None:
            if has_visible_tabs:
                self.detail_tab_hint.hide()
            elif self._is_returns_mode():
                self.detail_tab_hint.setText(orders_ui.ORDERS_DETAIL_RETURN_NO_EXTRA_ACTION_TEXT)
                self.detail_tab_hint.show()
            else:
                self.detail_tab_hint.setText(orders_ui.ORDERS_DETAIL_ORDER_NO_EXTRA_ACTION_TEXT)
                self.detail_tab_hint.show()

        if has_visible_tabs:
            current_idx = int(self.detail_tabs.currentIndex())
            if current_idx not in visible_indexes:
                self.detail_tabs.setCurrentIndex(visible_indexes[0])

    def _schedule_workspace_editor_refresh(self) -> None:
        self._workspace.schedule_editor_layout_refresh()

    def _active_selection_identity(self, order) -> str:
        if order is None:
            return "-"
        if self._is_returns_mode():
            return str(
                getattr(order, "claimNumber", "")
                or getattr(order, "claimId", "")
                or getattr(order, "orderNumber", "-")
                or "-"
            )
        return str(getattr(order, "orderNumber", "-") or "-")

    def _workspace_record_key(self, order) -> str:
        if order is None:
            return ""
        if self._is_returns_mode():
            return str(
                getattr(order, "claimId", "")
                or getattr(order, "claimNumber", "")
                or getattr(order, "orderNumber", "")
                or ""
            ).strip()
        return str(getattr(order, "orderNumber", "") or "").strip()

    def _sync_workspace_panel_header(self) -> None:
        if self._selection_mode == "bulk":
            title = orders_ui.ORDERS_BULK_RETURNS_TITLE if self._is_returns_mode() else orders_ui.ORDERS_BULK_ORDERS_TITLE
            selected_count = len(self.list_widget.get_selected_orders() or [])
            if selected_count > 0:
                subtitle = orders_ui.ORDERS_BULK_SELECTED_TEMPLATE.format(
                    entity=self._entity_singular,
                    count=selected_count,
                )
            else:
                subtitle = (
                    orders_ui.ORDERS_BULK_SELECT_RETURN_HINT
                    if self._is_returns_mode()
                    else orders_ui.ORDERS_BULK_SELECT_ORDER_HINT
                )
            self._workspace.set_left_title(title)
            self._workspace.set_left_subtitle(subtitle)
            return

        title = orders_ui.ORDERS_RETURN_DETAIL_TITLE if self._is_returns_mode() else orders_ui.ORDERS_DETAIL_ORDER_EDIT_TITLE
        if self._active_order is None:
            subtitle = (
                orders_ui.ORDERS_DETAIL_SELECT_RETURN_HINT
                if self._is_returns_mode()
                else orders_ui.ORDERS_DETAIL_SELECT_ORDER_HINT
            )
        else:
            subtitle = orders_ui.ORDERS_BULK_SELECTED_TEMPLATE.format(
                entity=self._entity_singular,
                count=self._active_selection_identity(self._active_order),
            )
        self._workspace.set_left_title(title)
        self._workspace.set_left_subtitle(subtitle)

    def _refresh_selection_side_panel(self):
        self._sync_workspace_panel_header()
        if self._selection_mode == "bulk":
            bulk_title = orders_ui.ORDERS_BULK_RETURNS_TITLE if self._is_returns_mode() else orders_ui.ORDERS_BULK_ORDERS_TITLE
            if self._is_returns_mode():
                self.selection_title.setText(bulk_title)
            else:
                self.selection_title.setText(str(ui_text("orders.selection_panel.title_bulk", bulk_title)))
        else:
            detail_title = orders_ui.ORDERS_RETURN_DETAIL_TITLE if self._is_returns_mode() else orders_ui.ORDERS_DETAIL_ORDER_EDIT_TITLE
            if self._is_returns_mode():
                self.selection_title.setText(detail_title)
            else:
                self.selection_title.setText(str(ui_text("orders.selection_panel.title_detail", detail_title)))

        selected = self.list_widget.get_selected_orders() or []
        count = len(selected)
        if self._selection_mode == "bulk":
            if count <= 0:
                self._refresh_bulk_cargo_provider_options([])
                self._refresh_bulk_overview([])
                self.selection_stack.setCurrentIndex(0)
                self.btn_bulk_print.setEnabled(False)
                self.btn_bulk_change_cargo_provider.setEnabled(False)
                self._sync_active_card_spin_state()
                self._update_selection_lock_state()
                self._schedule_workspace_editor_refresh()
                return

            self._refresh_bulk_cargo_provider_options(selected)
            self._refresh_bulk_overview(selected)
            self.selection_stack.setCurrentIndex(2)
            self.btn_bulk_print.setEnabled((count > 0) and (not self._is_returns_mode()))
            self.btn_bulk_change_cargo_provider.setEnabled((count > 0) and (not self._is_returns_mode()))
            self.bulk_tabs.setCurrentIndex(0)
            self._sync_active_card_spin_state()
            self._update_selection_lock_state()
            self._schedule_workspace_editor_refresh()
            return

        # detail mode
        detail_order = self._active_order
        if detail_order is not None:
            all_orders = self.list_widget.filtered_orders or []
            if detail_order not in all_orders:
                target_no = self._workspace_record_key(detail_order)
                detail_order = next(
                    (o for o in all_orders if self._workspace_record_key(o) == target_no),
                    None,
                )
                self._active_order = detail_order

        if detail_order is None:
            self.selection_stack.setCurrentIndex(0)
            self.btn_change_cargo_provider.setEnabled(False)
            self.btn_detail_print.setEnabled(False)
            self._sync_detail_tab_visibility(None)
            self._refresh_detail_cargo_provider_options(None)
            if self.btn_approve_return is not None:
                self.btn_approve_return.setEnabled(False)
            if self.return_approval_hint is not None:
                self.return_approval_hint.setText(
                    orders_ui.ORDERS_DETAIL_RETURN_APPROVAL_HINT
                )
            self.detail_order_no.setText(orders_ui.ORDERS_EMPTY_VALUE_TEXT)
            self.detail_customer.setText(orders_ui.ORDERS_EMPTY_VALUE_TEXT)
            self.detail_phone.setText(orders_ui.ORDERS_EMPTY_VALUE_TEXT)
            self.detail_status.setText(orders_ui.ORDERS_EMPTY_VALUE_TEXT)
            self.detail_cargo.setText(orders_ui.ORDERS_EMPTY_VALUE_TEXT)
            self.detail_tracking_no.setText(orders_ui.ORDERS_EMPTY_VALUE_TEXT)
            self.detail_amount.setText(orders_ui.ORDERS_EMPTY_VALUE_TEXT)
            self.detail_date.setText(orders_ui.ORDERS_EMPTY_VALUE_TEXT)
            self.detail_address.setText(orders_ui.ORDERS_EMPTY_VALUE_TEXT)
            self.detail_items_table.setRowCount(0)
            empty_items_default = (
                "Bu iade için ürün satırı bulunamadı."
                if self._is_returns_mode()
                else "Bu sipariş için ürün satırı bulunamadı."
            )
            empty_items_text = (
                empty_items_default
                if self._is_returns_mode()
                else str(ui_text("orders.selection_panel.detail.items_empty", empty_items_default))
            )
            self.detail_items_hint.setText(empty_items_text)
            self.detail_items_hint.show()
            self.detail_tabs.setCurrentIndex(0)
            self._sync_active_card_spin_state()
            self._update_selection_lock_state()
            self._schedule_workspace_editor_refresh()
            return

        first = str(getattr(detail_order, "customerFirstName", "") or "").strip()
        last = str(getattr(detail_order, "customerLastName", "") or "").strip()
        customer = " ".join(v for v in [first, last] if v).strip() or "-"
        shipment = self._coerce_dict(getattr(detail_order, "shipmentAddress", None))
        recipient = self._first_non_empty(
            shipment.get("fullName"),
            shipment.get("contactName"),
            shipment.get("receiverName"),
            shipment.get("firstName"),
            default="",
        ).strip()
        if customer == "-" and recipient:
            customer = recipient
        phone_text, address_text = self._extract_order_contact_and_address(detail_order)
        if self._is_returns_mode():
            detail_no = str(
                getattr(detail_order, "claimNumber", "")
                or getattr(detail_order, "claimId", "")
                or getattr(detail_order, "orderNumber", "-")
                or "-"
            )
        else:
            detail_no = str(getattr(detail_order, "orderNumber", "-") or "-")
        self.detail_order_no.setText(detail_no)
        self.detail_customer.setText(customer)
        cargo_text = str(getattr(detail_order, "cargoProviderName", "-") or "-")
        self.detail_cargo.setText(cargo_text)
        self._refresh_detail_cargo_provider_options(detail_order, cargo_text)
        self._sync_detail_cargo_provider_selection(cargo_text)
        self.detail_phone.setText(phone_text)
        self.detail_tracking_no.setText(str(getattr(detail_order, "cargoTrackingNumber", "-") or "-"))
        status_code = str(getattr(detail_order, "shipmentPackageStatus", None) or getattr(detail_order, "status", "-") or "-")
        self.detail_status.setText(format_order_status(status_code))
        self.detail_amount.setText(self._format_money(getattr(detail_order, "totalPrice", None)))
        self.detail_date.setText(self._format_order_date(detail_order))
        self.detail_address.setText(address_text)
        self._fill_detail_items_table(detail_order)
        self.selection_stack.setCurrentIndex(1)
        self._sync_detail_tab_visibility(detail_order)
        self.btn_change_cargo_provider.setEnabled(self._can_change_cargo_for_order(detail_order))
        self.btn_detail_print.setEnabled(self._can_print_order(detail_order))
        if self.btn_approve_return is not None:
            can_approve = self._can_approve_active_return()
            self.btn_approve_return.setEnabled(can_approve)
            if self.return_approval_hint is not None:
                if can_approve:
                    self.return_approval_hint.setText(
                        orders_ui.ORDERS_DETAIL_RETURN_APPROVAL_READY_HINT
                    )
                else:
                    self.return_approval_hint.setText(
                        orders_ui.ORDERS_DETAIL_RETURN_APPROVAL_HINT
                    )
        self._sync_active_card_spin_state()
        self._update_selection_lock_state()
        self._schedule_workspace_editor_refresh()

    # ------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------
    def _setup_styles(self):
        self.setObjectName("OrdersManagerRoot")
        self.setStyleSheet(compose_record_workspace_style("""
        QWidget#OrdersManagerRoot {
            background-color: #F3F4F6;
            color: #111827;
        }

        QFrame#HeaderCard {
            border-radius: 14px;
            border: none;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #111827, stop:1 #020617);
        }
        QLabel#HeaderTitle { font-size: 16px; font-weight: 700; color: #F9FAFB; }
        QLabel#HeaderSubtitle { font-size: 11px; color: #E5E7EB; }

        QPushButton#HeaderGhostBtn {
            padding: 6px 10px;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.18);
            background: rgba(255,255,255,0.08);
            color: #F9FAFB;
            font-weight: 600;
        }
        QPushButton#HeaderGhostBtn:hover { background: rgba(255,255,255,0.12); }

        QFrame#Card {
            background-color: #FFFFFF;
            border-radius: 12px;
            border: 1px solid #E5E7EB;
        }
        QFrame#Card[modeActive="true"] {
            border: 2px solid #3B82F6;
        }
        QFrame#RightCard {
            background-color: #FFFFFF;
            border-radius: 12px;
            border: 1px solid #E5E7EB;
            min-width: 240px;
        }

        QLabel#CardTitle { font-size: 12px; font-weight: 700; color: #111827; }
        QLabel#CardHint { font-size: 11px; color: #6B7280; }
        QLabel#Muted { font-size: 11px; color: #6B7280; }
        QLabel#PaginationStrong {
            font-size: 13px;
            font-weight: 800;
            color: #0F172A;
        }
        QLabel#InlineLabel { font-size: 11px; color: #374151; font-weight: 600; }

        QLineEdit#Input {
            padding: 7px 10px;
            border-radius: 10px;
            border: 1px solid #E5E7EB;
            background: #FFFFFF;
        }
        QLineEdit#Input:focus { border: 1px solid #93C5FD; }

        QComboBox#Combo {
            padding: 6px 10px;
            border-radius: 10px;
            border: 1px solid #E5E7EB;
            background: #FFFFFF;
        }
        QPushButton#PrimaryBtn,
        QPushButton#Primary {
            padding: 7px 12px;
            min-height: 40px;
            border-radius: 10px;
            border: 1px solid #0EA5E9;
            background-color: #0EA5E9;
            color: white;
            font-weight: 700;
        }
        QPushButton#PrimaryBtn:hover,
        QPushButton#Primary:hover { background-color: #0284C7; border-color: #0284C7; }
        QPushButton#PrimaryBtn:disabled,
        QPushButton#Primary:disabled {
            border: 1px solid #93C5FD;
            background-color: #E0F2FE;
            color: #075985;
        }

        QPushButton#GhostBtn {
            padding: 6px 10px;
            border-radius: 10px;
            border: 1px solid #E5E7EB;
            background: #FFFFFF;
            font-weight: 600;
        }
        QPushButton#GhostBtn:hover { background: #F3F4F6; }

        QPushButton#SoftDanger {
            background: rgba(239, 68, 68, 0.12);
            color: #B91C1C;
            border: 1px solid rgba(239, 68, 68, 0.28);
            border-radius: 12px;
            padding: 11px 14px;
            font-weight: 900;
        }
        QPushButton#SoftDanger:hover {
            background: rgba(239, 68, 68, 0.18);
            border: 1px solid rgba(239, 68, 68, 0.42);
        }

        QFrame#BottomBar {
            background-color: #F9FAFB;
            border-radius: 10px;
            border: 1px solid #E5E7EB;
        }

        QPushButton#NavBtn {
            border-radius: 12px;
            border: 1px solid #E5E7EB;
            background: #FFFFFF;
            font-weight: 800;
        }
        QPushButton#NavBtn:hover {
            background: #EEF2FF;
            border-color: #C7D2FE;
        }

        QWidget#OrdersManagerRoot QScrollBar:vertical {
            background: transparent;
            width: 10px;
            margin: 2px 0px 2px 0px;
        }
        QWidget#OrdersManagerRoot QScrollBar::handle:vertical {
            background: rgba(15, 23, 42, 0.18);
            border-radius: 5px;
            min-height: 24px;
        }
        QWidget#OrdersManagerRoot QScrollBar::handle:vertical:hover {
            background: rgba(59, 130, 246, 0.45);
        }
        QWidget#OrdersManagerRoot QScrollBar::add-page:vertical,
        QWidget#OrdersManagerRoot QScrollBar::sub-page:vertical,
        QWidget#OrdersManagerRoot QScrollBar::add-page:vertical:hover,
        QWidget#OrdersManagerRoot QScrollBar::sub-page:vertical:hover,
        QWidget#OrdersManagerRoot QScrollBar::add-page:vertical:pressed,
        QWidget#OrdersManagerRoot QScrollBar::sub-page:vertical:pressed {
            background: transparent;
            border: none;
        }
        QWidget#OrdersManagerRoot QScrollBar::add-line:vertical,
        QWidget#OrdersManagerRoot QScrollBar::sub-line:vertical {
            height: 0px;
            background: transparent;
            border: none;
        }
        """))

    # ============================================================
    # Selection changes
    # ============================================================
    def _on_selection_changed(self):
        self._update_label()
        self._update_pagination_ui()
        self._refresh_selection_side_panel()

    def _update_action_button_state(self):
        if self._is_returns_mode():
            self.btn_detail_print.setEnabled(False)
            self.btn_bulk_print.setEnabled(False)
            self.btn_change_cargo_provider.setEnabled(False)
            self.btn_bulk_change_cargo_provider.setEnabled(False)
            if self.btn_approve_return is not None:
                self.btn_approve_return.setEnabled(self._can_approve_active_return())
            return
        selected_count = len(self.list_widget.get_selected_orders() or [])
        self.btn_detail_print.setEnabled(self._can_print_order(self._active_order))
        self.btn_change_cargo_provider.setEnabled(self._can_change_cargo_for_order(self._active_order))
        self.btn_bulk_print.setEnabled(selected_count > 0)
        self.btn_bulk_change_cargo_provider.setEnabled(selected_count > 0)

    def _can_approve_active_return(self) -> bool:
        if not self._is_returns_mode():
            return False
        order = self._active_order
        if order is None:
            return False
        waiting_ids = getattr(order, "waitingClaimLineItemIds", None) or []
        if not any(str(row or "").strip() for row in waiting_ids):
            return False
        status_code = str(getattr(order, "claimItemStatus", "") or getattr(order, "status", "") or "").strip()
        return status_code.casefold() == "waitinginaction"

    def _on_approve_return_clicked(self) -> None:
        if not self._is_returns_mode():
            return
        order = self._active_order
        if order is None:
            MessageHandler.show(self, Result.fail("Önce bir iade seçmelisin.", close_dialog=False), only_errors=True)
            return

        result = approve_return_claim(
            order,
            date_from=self.date_range.dateFrom().toPyDate(),
            date_to=self.date_range.dateTo().toPyDate(),
        )
        MessageHandler.show(self, result, only_errors=False)
        if result.success:
            self._order_items_cache.clear()
            self._order_profit_catalog = None
            self._order_profit_catalog_account_ids = set()
            self._active_order = None
            self.list_widget.clear_active_order()
            self.list_widget.reload_orders()

    # ============================================================
    # Printing action
    # ============================================================
    def _on_action_button_clicked(self):
        if self._is_returns_mode():
            MessageHandler.show(
                self,
                Result.fail("İade kayıtlarında yazdırma işlemi desteklenmiyor.", close_dialog=False),
                only_errors=True,
            )
            return
        chosen_orders = self.get_selected_orders()
        if not chosen_orders and self._active_order is not None:
            chosen_orders = [self._active_order]
        if not chosen_orders:
            return
        from Labels.views.views import LabelPrintManagerWindow

        self.label_window = LabelPrintManagerWindow(self)
        self.label_window.exec()
        self.label_window.setWindowModality(Qt.WindowModality.NonModal)
        self.label_window.raise_()
        self.label_window.activateWindow()

    # ============================================================
    # Pagination
    # ============================================================
    def _update_pagination_ui(self):
        total = len(self.list_widget.filtered_orders or [])
        page_size = self.list_widget.page_size

        if total == 0:
            total_pages = 1
            current = 0
        else:
            total_pages = (total + page_size - 1) // page_size
            current = self.list_widget.current_page

        try:
            self.pagination_label.setText(
                f"Sayfa <b>{current}/{total_pages}</b> | Toplam: {total} kayıt"
            )
            self.prev_page_btn.setEnabled(current > 1)
            self.next_page_btn.setEnabled(current < total_pages)
            self._workspace.set_records_summary_text(f"{self.list_widget.shown_count()} / {total} kayıt")
        except RuntimeError:
            return

    def _on_page_size_changed(self, text: str):
        try:
            size = int(text)
        except ValueError:
            size = 20
        self.list_widget.set_page_size(size)
        self._update_label()
        self._update_pagination_ui()

    def _on_prev_page(self):
        self.list_widget.prev_page()
        self._update_label()
        self._update_pagination_ui()

    def _on_next_page(self):
        self.list_widget.next_page()
        self._update_label()
        self._update_pagination_ui()

    # ============================================================
    # Filters
    # ============================================================
    def _refresh_cargo_filter(self, _orders=None):
        preferred_cargo = str(self.cargo_filter.currentText() or "").strip()
        platform_code = str(self.platform_filter.currentData() or "").strip()
        res = refresh_cargo_filter(
            self.cargo_filter,
            self.list_widget.orders,
            platform_code=platform_code,
            preferred_cargo=preferred_cargo,
        )
        MessageHandler.show(self, res, only_errors=True)

    @staticmethod
    def _order_platform_code(order) -> str:
        return resolve_order_platform_code(order)

    def _refresh_detail_cargo_provider_options(self, order=None, preferred_name_or_code: str = "") -> None:
        platform_code = self._order_platform_code(order or self._active_order)
        current_code = cargo_provider_code_for_name(preferred_name_or_code, platform_code=platform_code)
        if not current_code:
            current_code = str(self.detail_cargo_provider_select.currentData() or "").strip().upper()

        with QSignalBlocker(self.detail_cargo_provider_select):
            self.detail_cargo_provider_select.clear()
            for row in list_changeable_cargo_providers(platform_code or None):
                code = str(row.get("code") or "").strip().upper()
                name = str(row.get("name") or "").strip()
                if code and name:
                    self.detail_cargo_provider_select.addItem(f"{name} ({code})", data=code)

        if current_code:
            idx = self.detail_cargo_provider_select.findData(current_code)
            if idx >= 0:
                self.detail_cargo_provider_select.setCurrentIndex(idx)

    def _refresh_bulk_cargo_provider_options(self, orders: list | None = None) -> None:
        rows = list(orders or self.list_widget.get_selected_orders() or [])
        platform_codes: set[str] = set()
        for order in rows:
            platform_code = self._order_platform_code(order)
            if platform_code:
                platform_codes.add(platform_code)
        platform_code = next(iter(platform_codes)) if len(platform_codes) == 1 else ""
        current_code = str(self.bulk_cargo_provider_select.currentData() or "").strip().upper()

        with QSignalBlocker(self.bulk_cargo_provider_select):
            self.bulk_cargo_provider_select.clear()
            for row in list_changeable_cargo_providers(platform_code or None):
                code = str(row.get("code") or "").strip().upper()
                name = str(row.get("name") or "").strip()
                if code and name:
                    self.bulk_cargo_provider_select.addItem(f"{name} ({code})", data=code)

        if current_code:
            idx = self.bulk_cargo_provider_select.findData(current_code)
            if idx >= 0:
                self.bulk_cargo_provider_select.setCurrentIndex(idx)

    def _refresh_order_status_filter(self, _orders=None):
        current_code = str(self.order_status_filter.currentData() or "").strip()
        current_label = str(self.order_status_filter.currentText() or "").strip()
        had_selection = bool(current_code or current_label)
        if self._is_returns_mode():
            current_code = str(self.order_status_filter.currentData() or "").strip()
            if current_code.casefold() == "all":
                current_code = ""
            current_label = str(self.order_status_filter.currentText() or "").strip()
            if current_label.casefold() == "tümü":
                current_label = ""
            res = refresh_order_status_filter(
                self.order_status_filter,
                self.list_widget.orders,
                default_status_code=current_code or None,
                default_status_label=current_label or None,
                include_known_statuses=False,
            )
        else:
            res = refresh_order_status_filter(
                self.order_status_filter,
                self.list_widget.orders,
                default_status_code=current_code or None,
                default_status_label=current_label or None,
                include_known_statuses=True,
            )
        MessageHandler.show(self, res, only_errors=True)
        if not had_selection:
            self._apply_default_order_status_selection()

    def _trigger_debounce(self):
        self.filter_timer.start(320)

    def _clear_filters_and_apply(self):
        signal_widgets = (
            self.global_search,
            self.search_input,
            self.customer_input,
            self.tracking_input,
            self.amount_min_input,
            self.amount_max_input,
            self.cargo_filter,
            self.platform_filter,
            self.processed_filter,
            self.order_status_filter,
            self.deadline_filter,
        )
        with _signals_blocked(*signal_widgets):
            try:
                self.date_range.setSignalsBlocked(True)
                self.global_search.clear()
                self.search_input.clear()
                self.customer_input.clear()
                self.tracking_input.clear()
                self.amount_min_input.clear()
                self.amount_max_input.clear()
                self.cargo_filter.setCurrentText("Tümü")
                self.platform_filter.setCurrentText("Tümü")
                self.processed_filter.setCurrentText("Tümü")
                if self._is_returns_mode():
                    self.order_status_filter.setCurrentText("Aksiyon Bekliyor")
                else:
                    self.order_status_filter.setCurrentText("Tümü")
                self.deadline_filter.setCurrentText("Tümü")
                self._apply_default_filter_date_range()
            finally:
                self.date_range.setSignalsBlocked(False)

        self.apply_filters()

    def apply_filters(self):
        try:
            if self._closing:
                return
            self._sync_default_filter_date_range_if_unmodified()
            self._filter_request_seq += 1
            seq = int(self._filter_request_seq)
            reload_seq = int(self.list_widget._reload_seq)
            filters = {
                "global": self.global_search.text().strip(),
                "order_no": self.search_input.text().strip(),
                "cargo": self.cargo_filter.currentText() or "Tümü",
                "platform": self.platform_filter.currentText() or "Tümü",
                "platform_code": self.platform_filter.currentData() or "",
                "customer": self.customer_input.text().strip(),
                "tracking_no": self.tracking_input.text().strip(),
                "shipment_status": self.order_status_filter.currentText() or "Tümü",
                "shipment_status_code": self.order_status_filter.currentData() or "",
                "deadline_label": self.deadline_filter.currentText() or "Tümü",
                "deadline_category": self.deadline_filter.currentData() or "all",
                "processed_label": self.processed_filter.currentText() or "Tümü",
                "amount_min": self.amount_min_input.text().strip(),
                "amount_max": self.amount_max_input.text().strip(),
                "date_enabled": True,
                "date_from": self.date_range.dateFrom().toPyDate(),
                "date_to": self.date_range.dateTo().toPyDate(),
                "processed_mode": self.processed_filter.currentData() or "all",
            }

            if self._is_returns_mode():
                remote_signature = self._current_returns_remote_signature()
                if self._returns_remote_signature != remote_signature:
                    self._returns_remote_signature = remote_signature
                    self._last_applied_filter_signature = None
                    self.list_widget.reload_orders()
                    return
            else:
                source_signature = self._current_orders_source_signature()
                if self._orders_source_signature != source_signature:
                    self._orders_source_signature = source_signature
                    self._last_applied_filter_signature = None
                    self.list_widget.reload_orders()
                    return

            signature: tuple[object, ...] = (
                str(filters["global"]).casefold(),
                str(filters["order_no"]).casefold(),
                str(filters["cargo"]),
                str(filters["platform"]),
                str(filters["platform_code"]),
                str(filters["customer"]).casefold(),
                str(filters["tracking_no"]).casefold(),
                str(filters["shipment_status"]),
                str(filters["shipment_status_code"]),
                str(filters["deadline_label"]),
                str(filters["deadline_category"]),
                str(filters["processed_label"]),
                str(filters["amount_min"]),
                str(filters["amount_max"]),
                str(filters["date_from"]),
                str(filters["date_to"]),
                str(filters["processed_mode"]),
                reload_seq,
            )

            if signature == self._last_applied_filter_signature:
                self._update_label()
                self._update_pagination_ui()
                self._update_date_status()
                self._refresh_selection_side_panel()
                return

            status_info_key = "iade" if self._is_returns_mode() else "sipariş"
            deadline_info = ""
            if not self._is_returns_mode():
                deadline_info = f" | süre={filters['deadline_label']}"
            self.lbl_filter_info.setText(
                f"Filtre: platform={filters['platform']} | kargo={filters['cargo']} | işlenme={filters['processed_label']} | {status_info_key}={filters['shipment_status']}{deadline_info}"
            )
            self.date_range.setStatus("neutral")
            loading_text = "İadeler filtreleniyor..." if self._is_returns_mode() else "Siparişler filtreleniyor..."
            self.list_widget.set_list_loading(True, loading_text)

            self.filter_worker = start_filter_worker(self, self.list_widget, filters, apply_on_result=False)
            worker = self.filter_worker
            self._filter_workers.append(worker)

            def _after_filter(_res: Result):
                if self._closing:
                    return
                if seq != self._filter_request_seq:
                    return
                if not getattr(_res, "success", False):
                    MessageHandler.show(self, _res, only_errors=True)
                    self.selected_count_label.setText(orders_ui.ORDERS_FILTER_FAILED_TEXT)
                else:
                    filtered = (_res.data or {}).get("filtered", []) or []
                    self.list_widget.apply_filter_result(filtered)
                    self.list_widget.filtered_orders = filtered
                    self.selected_count_label.setText(f"Filtre tamamlandı. (Kalan: {len(filtered)})")
                    self._last_applied_filter_signature = signature
                self._update_label()
                self._update_pagination_ui()
                self._update_date_status()
                self._refresh_selection_side_panel()
                self.list_widget.set_list_loading(False)

            def _after_filter_finished():
                try:
                    self._filter_workers.remove(worker)
                except ValueError:
                    pass
                if self.filter_worker is worker:
                    self.filter_worker = None
                if not self._closing and seq == self._filter_request_seq:
                    self.list_widget.set_list_loading(False)
                worker.deleteLater()

            worker.result_ready.connect(_after_filter)
            worker.finished.connect(_after_filter_finished)
            worker.start()

        except Exception as e:
            MessageHandler.show(self, Result.fail(map_error_to_message(e), error=e), only_errors=True)
            self.list_widget.set_list_loading(False)

    def _update_date_status(self):
        try:
            filtered = len(self.list_widget.filtered_orders or [])
        except Exception:
            filtered = 0
        self.date_range.setStatus("ok" if filtered > 0 else "bad")

    # ============================================================
    # Label & bulk selection
    # ============================================================
    def _update_label(self):
        self._sync_bulk_toggle_button_state()
        self._update_action_button_state()

    def _sync_bulk_toggle_button_state(self):
        filtered_orders = self.list_widget.filtered_orders or []
        total = len(filtered_orders)
        selected = 0
        for order in filtered_orders:
            try:
                if bool(getattr(order, "_selected", False)):
                    selected += 1
            except Exception:
                continue
        self.btn_bulk_select_toggle.setSelectionCounts(selected, total)

    def _on_bulk_toggle_action(self, action: str):
        mode = str(action or "").strip().lower()
        if mode == "clear":
            self.deselect_all()
            return
        self.select_all()
    def select_all(self):
        for o in (self.list_widget.filtered_orders or []):
            setattr(o, "_selected", True)
        self._selection_mode = "bulk"
        self.list_widget._safe_build(self.list_widget.filtered_orders)
        self.list_widget._emit_selection_signals_if_needed(force=True)

    def deselect_all(self):
        for o in (self.list_widget.filtered_orders or []):
            setattr(o, "_selected", False)
        self.list_widget._safe_build(self.list_widget.filtered_orders)
        self.list_widget._emit_selection_signals_if_needed(force=True)

    def get_selected_orders(self):
        return self.list_widget.get_selected_orders()


class OrdersWorkspaceBehaviorAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, window: "OrdersManagerWindow") -> None:
        self.window = window
        self.new_panel_id = None
        self.edit_panel_id = "edit"
        self.bulk_panel_id = "bulk"
        self.clear_active_on_close = True

    @property
    def list_widget(self):
        return self.window.list_widget

    def get_mode(self) -> str:
        mode = str(getattr(self.window, "_selection_mode", "detail") or "detail")
        return "edit" if mode == "detail" else mode

    def set_mode(self, mode: str) -> None:
        self.window._selection_mode = "detail" if mode == "edit" else mode

    def get_active_key(self) -> str:
        return self.window._workspace_record_key(getattr(self.window, "_active_order", None))

    def get_selected_count(self) -> int:
        return len(self.window.list_widget.get_selected_orders() or [])

    def get_record_key(self, record) -> str:
        return self.window._workspace_record_key(record)

    def prepare_new(self) -> None:
        return

    def activate_record(self, record) -> None:
        self.window._active_order = record
        self.window.list_widget.set_active_order(record)

    def clear_active(self) -> None:
        self.window._active_order = None
        self.window.list_widget.clear_active_order()

    def apply_selection(self, record, selected: bool) -> None:
        self.window.list_widget.set_order_selected(record, bool(selected))

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self.window.list_widget.set_select_button_guide_enabled(bool(enabled))

    def on_state_changed(self) -> None:
        self.window._sync_workspace_behavior_state()

    def edit_guidance_message(self) -> str:
        detail_guidance_default = (
            "Detayları görmek için sağdaki listeden bir iade seç."
            if self.window._is_returns_mode()
            else "Detayları görmek için sağdaki listeden bir sipariş seç."
        )
        if self.window._is_returns_mode():
            return detail_guidance_default
        return str(ui_text("orders.selection_panel.overlay_detail", detail_guidance_default))

    def bulk_guidance_message(self) -> str:
        bulk_guidance_default = (
            "Toplu işlem için sağdaki listeden en az bir iadeyi SEÇ ile işaretle."
            if self.window._is_returns_mode()
            else "Toplu işlem için sağdaki listeden en az bir siparişi SEÇ ile işaretle."
        )
        if self.window._is_returns_mode():
            return bulk_guidance_default
        return str(ui_text("orders.selection_panel.overlay_bulk", bulk_guidance_default))


# ============================================================
# 3. OrdersTab
# ============================================================

