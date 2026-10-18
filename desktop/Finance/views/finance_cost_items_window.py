
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from PyQt6.QtCore import Qt, QAbstractListModel, QDate, QModelIndex, QRect, QSize, QSignalBlocker, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QLabel,
    QFrame,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QCheckBox,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QListView,
    QStackedWidget,
    QStyle,
)

from Account.signals.signals import account_signals
from Core.threads.async_worker import AsyncWorker
from Core.threads.sync_worker import SyncWorker
from Core.views import (
    AppMessageCenter,
    CircularProgressButton,
    CircularPercentageInput,
    CurrencyAmountInput,
    DateSelector,
    ActionPulseButton,
    BadgeButton,
    SwitchSelectWidget,
    SwitchButton,
    NumericPulseLineEdit,
    NumericRangeGlowInput,
    RecordWorkspaceBehaviorAdapter,
    RecordWorkspaceScaffold,
)
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from settings import ASSETS_DIR
from Finance.constants.ui_constants import (
    FINANCE_COST_ITEM_ACCEPT_BUTTON_TEXT,
    FINANCE_COST_ITEM_ACCEPT_CONFIRMATION_TEXT,
    FINANCE_COST_ITEM_ACCEPT_TITLE,
    FINANCE_COST_ITEM_PENDING_BADGE_TEXT,
    FINANCE_COST_ITEM_SELECT_BUTTON_TEXT,
    FINANCE_COST_ITEM_SELECTED_BUTTON_TEXT,
)
from Core.views import (
    RECORD_WORKSPACE_STYLE as FINANCE_STYLE,
    RecordWorkspaceCardRecord as OrdersStyleCardRecord,
    RecordWorkspaceListDelegate as OrdersStyleListDelegate,
    RecordWorkspaceListModel as OrdersStyleListModel,
    RecordWorkspaceListWidget as OrdersStyleListWidget,
)


def _compact_text(value: object) -> str:
    return str(value or "").strip()


def _finance_action(name: str):
    from Finance.views import actions

    return getattr(actions, name)


def _finance_domain_constant(name: str):
    from Finance.constants import domain_constants

    return getattr(domain_constants, name)


def _finance_cost_value_type_options() -> tuple[tuple[str, str], ...]:
    return tuple(_finance_domain_constant("FINANCE_COST_VALUE_TYPE_OPTIONS"))


def _finance_currency_options() -> tuple[str, ...]:
    return tuple(_finance_domain_constant("FINANCE_CURRENCY_OPTIONS"))


def cost_source_type_label(*args, **kwargs):
    from Finance.processors.pipeline import cost_source_type_label as _cost_source_type_label

    return _cost_source_type_label(*args, **kwargs)


def normalize_cost_source_type(*args, **kwargs):
    from Finance.processors.pipeline import normalize_cost_source_type as _normalize_cost_source_type

    return _normalize_cost_source_type(*args, **kwargs)


def finance_cost_rule_label(*args, **kwargs):
    return _finance_domain_constant("finance_cost_rule_label")(*args, **kwargs)


def finance_cost_calculation_options(*, include_all: bool = True) -> list[tuple[str, str]]:
    options = list(_finance_cost_value_type_options())
    return ([("Tümü", "")] + options) if include_all else options


def finance_cost_item_platform_options(*, include_all: bool = False, db_name: str | None = None) -> list[tuple[str, str]]:
    from Core.db.models import coerce_source_id
    from Marketplaces.constants.catalog_constants import marketplace_records

    options = [
        (
            _compact_text(row.get("label")),
            str(coerce_source_id(row.get("sourceId") or row.get("source_id")) or ""),
        )
        for row in marketplace_records(db_name=db_name)
        if _compact_text(row.get("label")) and coerce_source_id(row.get("sourceId") or row.get("source_id")) is not None
    ]
    return ([("Tümü", "")] + options) if include_all else options


def _normalize_finance_currency(value: object, *, fallback: str = "TRY") -> str:
    finance_currency_options = _finance_currency_options()
    code = _compact_text(value).upper()
    if code in finance_currency_options:
        return code
    fallback_code = _compact_text(fallback).upper()
    if fallback_code in finance_currency_options:
        return fallback_code
    return "TRY"


def finance_cost_currency(record: dict[str, Any] | None, default: str = "TRY") -> str:
    payload = dict(record or {})
    return _normalize_finance_currency(payload.get("currency"), fallback=default)


def finance_cost_amount_display(record: dict[str, Any] | None) -> str:
    return _finance_action("finance_cost_amount_display")(record)


def load_finance_cost_items(**kwargs):
    return _finance_action("load_finance_cost_items")(**kwargs)


def save_finance_cost_item(*args, **kwargs):
    return _finance_action("save_finance_cost_item")(*args, **kwargs)


def delete_finance_cost_item(*args, **kwargs):
    return _finance_action("delete_finance_cost_item")(*args, **kwargs)


def delete_finance_cost_items(*args, **kwargs):
    return _finance_action("delete_finance_cost_items")(*args, **kwargs)


def accept_finance_cost_item(*args, **kwargs):
    return _finance_action("accept_finance_cost_item")(*args, **kwargs)


class FinanceCostItemsListDelegate(OrdersStyleListDelegate):
    @staticmethod
    def _payload_for(index) -> dict[str, Any]:
        record = index.data(OrdersStyleListModel.RecordRole)
        payload = getattr(record, "payload", None)
        return dict(payload or {}) if isinstance(payload, dict) else {}

    def _is_pending_builtin_index(self, index) -> bool:
        payload = self._payload_for(index)
        return bool(payload.get("isBuiltin")) and not bool(payload.get("isBuiltinAccepted"))

    def _hook_text(self, index) -> str:
        if self._is_pending_builtin_index(index):
            return FINANCE_COST_ITEM_ACCEPT_BUTTON_TEXT
        return super()._hook_text(index)

    def _hook_rect_for_index(self, rect: QRect, index, view=None) -> QRect:
        if self._is_pending_builtin_index(index):
            return self._build_hook_rect(
                rect,
                view=view,
                hook_w=self._hook_width_for_index(index, minimum=88),
                hook_h=34,
            )
        return self._build_hook_rect(rect, view=view, hook_w=self._hook_w)

    def paint(self, painter: QPainter, option, index) -> None:
        if not self._is_pending_builtin_index(index):
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self._item_rect(option)
        row = index.row()
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected_flag = self._is_selected_index(index)
        hook_selected = self._is_hook_selected_index(index)
        active_flag = self._is_active_index(index)
        active_visible = active_flag and self._active_visual_enabled

        bg = QColor("#F3F4F6")
        border = QColor("#D1D5DB")
        if hovered:
            bg = QColor("#E5E7EB")
            border = QColor("#CBD5E1")
        if selected_flag or hook_selected or active_visible:
            bg = QColor("#E5E7EB")
            border = QColor("#94A3B8")

        painter.setBrush(bg)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 10, 10)

        if active_visible:
            spin_rect = rect.adjusted(1, 1, -1, -1)
            spin_pen = QPen(QColor("#64748B"), 2)
            spin_pen.setStyle(Qt.PenStyle.CustomDashLine)
            spin_pen.setDashPattern([9, 6])
            spin_pen.setDashOffset(-self._spin_phase)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(spin_pen)
            painter.drawRoundedRect(spin_rect, 10, 10)

        hook_rect = self._hook_rect_for_index(rect, index, option.widget)
        self._paint_pending_content(painter, rect, index, hook_rect)
        self._paint_hook_button(
            painter,
            hook_rect,
            index=index,
            row=row,
            hook_selected=False,
        )

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if not self._is_pending_builtin_index(index):
            return super().editorEvent(event, model, option, index)
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

    def _paint_pending_content(self, painter: QPainter, rect, index, hook_rect) -> None:
        title = index.data(OrdersStyleListModel.TitleRole) or ""
        subtitle = index.data(OrdersStyleListModel.SubtitleRole) or ""
        extra = index.data(OrdersStyleListModel.ExtraRole) or ""

        icon_rect = self._icon_rect(rect)
        self._paint_card_icon(painter, index, icon_rect)

        x = self._content_left(rect)
        text_width = self._text_width(rect, hook_rect)

        painter.setPen(QColor("#334155"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
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
            key_color=QColor("#475569"),
            value_color=QColor("#64748B"),
            point_size=8,
        )

        extra_rect = QRect(x, sub_rect.bottom() + 2, text_width, 18)
        self._draw_labeled_segments_line(
            painter,
            extra_rect,
            extra,
            key_color=QColor("#475569"),
            value_color=QColor("#6B7280"),
            point_size=8,
        )


class FinanceCostItemsListWidget(OrdersStyleListWidget):
    def __init__(self, parent=None, *, empty_placeholder_text: str):
        super().__init__(parent, empty_placeholder_text=empty_placeholder_text)
        self._delegate = FinanceCostItemsListDelegate(self, on_select_button=self._on_select_button_clicked)
        self.setItemDelegate(self._delegate)

class FinanceCostItemCard(QFrame):
    openRequested = pyqtSignal(int)
    selectionChanged = pyqtSignal(int, bool)

    def __init__(self, record: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.record = dict(record or {})
        self.record_pk = int(self.record.get("pk") or 0)
        self._picked = False
        self._active = False
        self._hovered = False
        self._dash_phase = 0.0
        self.setObjectName("FinanceListCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(6)

        title = QLabel(str(self.record.get("name") or "-"), objectName="InvoiceTitle")
        title.setWordWrap(True)
        text_col.addWidget(title)

        desc = QLabel(str(self.record.get("description") or "Açıklama yok."), objectName="InvoiceMeta")
        desc.setWordWrap(True)
        text_col.addWidget(desc)

        default_amount_text = finance_cost_amount_display(self.record)
        default_amount_label = str(self.record.get("defaultAmountLabel") or "Varsayılan")
        meta = QLabel(
            f"Değer Tipi: {self.record.get('valueTypeLabel', '-')} | "
            f"Varsayılan Kaynak: {self.record.get('defaultSourceTypeLabel', '-')} | "
            f"{default_amount_label}: {default_amount_text}",
            objectName="InvoiceMetaStrong",
        )
        meta.setWordWrap(True)
        text_col.addWidget(meta)

        amount_mode_text = str(self.record.get("amountModeText") or "KDV dahil")
        vat_suffix = ""
        if self.record.get("vatRateText"):
            vat_suffix = f" (%{self.record.get('vatRateText')})"
        flag_parts: list[str] = []
        amount_mode_part = f"{amount_mode_text}{vat_suffix}".strip()
        if amount_mode_part:
            flag_parts.append(amount_mode_part)
        flag_parts.append(f"Para Birimi: {finance_cost_currency(self.record)}")
        supported_platforms_text = str(self.record.get("supportedPlatformsText") or "").strip()
        if supported_platforms_text:
            flag_parts.append(f"Platformlar: {supported_platforms_text}")
        source_types_text = str(self.record.get("supportedSourceTypesText") or "").strip()
        if source_types_text:
            flag_parts.append(f"Kaynaklar: {source_types_text}")
        system_rule_label = str(self.record.get("systemRuleLabel") or "").strip()
        if system_rule_label:
            flag_parts.append(f"Sistem Kuralı: {system_rule_label}")
        flag_parts.append(f"Durum: {'Aktif' if self.record.get('isActive') else 'Pasif'}")
        flags = QLabel(" | ".join(flag_parts), objectName="InvoiceMeta")
        flags.setWordWrap(True)
        text_col.addWidget(flags)

        root.addLayout(text_col, 1)

        self.select_button = QPushButton(FINANCE_COST_ITEM_SELECT_BUTTON_TEXT, self)
        self.select_button.setObjectName("TariffSelectButton")
        self.select_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.select_button.setAutoDefault(False)
        self.select_button.setDefault(False)
        self.select_button.clicked.connect(self._toggle_selected)
        root.addWidget(self.select_button, alignment=Qt.AlignmentFlag.AlignVCenter)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)

        bg = QColor("#FFFFFF")
        border = QColor(0, 0, 0, 0)
        if self._hovered:
            bg = QColor("#F8FAFC")
            border = QColor("#E2E8F0")
        if self._active:
            bg = QColor("#EFF6FF")
            border = QColor("#60A5FA")

        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 16, 16)

        if self._active:
            spin_rect = rect.adjusted(2, 2, -2, -2)
            dash_pen = QPen(QColor("#2563EB"), 2)
            dash_pen.setStyle(Qt.PenStyle.CustomDashLine)
            dash_pen.setDashPattern([9, 6])
            dash_pen.setDashOffset(-self._dash_phase)
            painter.setPen(dash_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(spin_rect, 15, 15)

        super().paintEvent(event)

    def _emit_open(self) -> None:
        self.openRequested.emit(self.record_pk)

    def _toggle_selected(self) -> None:
        self._picked = not self._picked
        self.selectionChanged.emit(self.record_pk, self._picked)

    def mousePressEvent(self, event) -> None:
        self._emit_open()
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self.update()

    def advance_dash_phase(self, step: float = 1.0) -> None:
        self._dash_phase = (self._dash_phase + max(0.1, float(step))) % 1024.0
        if self._active:
            self.update()

    def set_picked(self, picked: bool) -> None:
        self._picked = bool(picked)
        self.select_button.setProperty("picked", bool(picked))
        self.select_button.setText(FINANCE_COST_ITEM_SELECTED_BUTTON_TEXT if picked else FINANCE_COST_ITEM_SELECT_BUTTON_TEXT)
        self.select_button.style().unpolish(self.select_button)
        self.select_button.style().polish(self.select_button)
        self.select_button.update()


class FinanceCostItemsWorkspaceAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, window: "FinanceCostItemsWindow") -> None:
        self.window = window

    @property
    def list_widget(self):
        return self.window.list_widget

    def get_mode(self) -> str:
        return str(getattr(self.window, "_left_mode", "edit") or "edit")

    def set_mode(self, mode: str) -> None:
        self.window._set_left_mode(mode)

    def get_active_key(self) -> str:
        return str(self.window._active_pk or "")

    def get_selected_count(self) -> int:
        return len(self.window._selected_pks)

    def get_record_key(self, record) -> str:
        return str(self.window._card_record_key(record) or "")

    def prepare_new(self) -> None:
        self.window._new_item(open_panel=False)

    def edit_without_active(self) -> None:
        self.window._load_editor_payload(None)

    def activate_record(self, record) -> None:
        self.window._workspace_activate_record(record)

    def clear_active(self) -> None:
        self.window._workspace_clear_active_record()

    def apply_selection(self, record, selected: bool) -> None:
        self.window._workspace_apply_selection(record, selected)

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self.window.list_widget.set_select_button_guide_enabled(bool(enabled))

    def on_state_changed(self) -> None:
        self.window._on_workspace_state_changed()

    def open_panel(self, shell) -> None:
        _ = shell
        self.window._open_left_panel()

    def close_panel(self, shell) -> None:
        _ = shell
        self.window._close_left_panel()

    def edit_guidance_message(self) -> str:
        return "Düzenlemek için sağdaki listeden bir maliyet kartı seç."

    def bulk_guidance_message(self) -> str:
        return "Toplu işlem için sağdaki listeden en az bir kartı SEÇ ile işaretle."


class FinanceCostItemsWindow(QWidget):
    itemsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("FinanceRoot")
        self.setStyleSheet(FINANCE_STYLE)
        self.setWindowTitle("Maliyet Kartları")
        self.setWindowIcon(QIcon(os.path.join(ASSETS_DIR, "finance-cost-items-icon.png")))
        self.setGeometry(220, 120, 1500, 860)

        self._has_loaded_once = False
        self._records: list[dict[str, object]] = []
        self._record_map: dict[int, dict[str, object]] = {}
        self._active_pk: int = 0
        self._selected_pks: set[int] = set()
        self._left_mode: str = "edit"
        self._left_stick_size = 620
        self._current_page = 1
        self._page_size = 50
        self._reload_worker: SyncWorker | None = None
        self._reload_pending = False
        self._reload_seq = 0

        self._search_timer = QTimer(self)
        self._search_timer.setInterval(250)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.request_reload_items)
        self._active_card_timer = QTimer(self)
        self._active_card_timer.setInterval(42)
        self._active_card_timer.timeout.connect(self._tick_active_card_animation)

        self._workspace = RecordWorkspaceScaffold(
            self,
            empty_placeholder_text="Gösterilecek maliyet kartı bulunamadı.",
            left_title="Düzenle",
            left_subtitle="Düzenlemek için sağdaki listeden bir maliyet kartı seç.",
            filters_title="Filtreler",
            filters_subtitle="Yazdıkça otomatik uygular.",
            records_title="Maliyet Kartları",
            records_subtitle="Finans maliyet katalog kayıtları",
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": "Yeni maliyet kartı",
                    "icon_path": str(ASSETS_DIR / "yeni-kayit.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": "Maliyet kartı düzenle",
                    "icon_path": str(ASSETS_DIR / "duzenleme-icon.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "bulk",
                    "text": "",
                    "tooltip": "Toplu seçim paneli",
                    "icon_path": str(ASSETS_DIR / "toplu-secim (2).png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
            ),
            shell_kwargs={
                "sidebar_width": 92,
                "left_stick_size": self._left_stick_size,
                "left_collapse_trigger": 430,
                "min_left_width": 380,
                "min_right_width": 280,
                "root_margins": (0, 0, 0, 0),
                "root_spacing": 8,
                "snap_on_drag": False,
            },
            page_size_options=(20, 50, 100, 250),
            style_sheet=FINANCE_STYLE,
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._workspace)

        self._workspace_shell = self._workspace.shell
        self._panel_sidebar = self._workspace.sidebar
        self._splitter = self._workspace_shell.splitter

        left_card = self._workspace.left_card
        self._left_panel_card = left_card
        self.left_panel_title = self._workspace.left_card.title_label
        self.left_panel_hint = self._workspace.left_card.subtitle_label
        self.editor_scroll = self._workspace.editor_scroll
        self.editor_actions_wrap = self._workspace.editor_actions_host
        self.bulk_panel = self._workspace.bulk_panel

        editor_host = QWidget(self)
        editor_host.setObjectName("FormBody")
        editor_layout = QFormLayout(editor_host)
        editor_layout.setContentsMargins(8, 4, 14, 6)
        editor_layout.setHorizontalSpacing(12)
        editor_layout.setVerticalSpacing(12)
        editor_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        editor_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        editor_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.cost_name_input = QLineEdit(self)
        self.cost_name_input.setObjectName("Input")
        self.cost_name_input.setPlaceholderText("Kart adı")
        self.cost_name_input.setMinimumHeight(42)
        editor_layout.addRow(QLabel("Ad *", objectName="FieldLabel"), self.cost_name_input)

        self.cost_description_input = QPlainTextEdit(self)
        self.cost_description_input.setObjectName("MethodText")
        self.cost_description_input.setPlaceholderText("Kart açıklaması")
        self.cost_description_input.setMinimumHeight(150)
        editor_layout.addRow(QLabel("Açıklama", objectName="FieldLabel"), self.cost_description_input)

        self.calc_combo = SwitchSelectWidget(
            self,
            multi=False,
            include_all=False,
            empty_text="Seçiniz",
        )
        self.calc_combo.setPlaceholderText("Değer tipi ara/seç")
        for label, key in finance_cost_calculation_options(include_all=False):
            self.calc_combo.addItem(label, key)
        self.calc_combo.setMinimumHeight(42)
        self.calc_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor_layout.addRow(QLabel("Değer Tipi", objectName="FieldLabel"), self.calc_combo)

        self.currency_combo = SwitchSelectWidget(self, multi=False, include_all=False, empty_text="Seçiniz")
        self.currency_combo.setPlaceholderText("Para birimi ara/seç")
        for currency in _finance_currency_options():
            self.currency_combo.addItem(currency, currency)
        self.currency_combo.setMinimumHeight(42)
        self.currency_combo.setMinimumWidth(120)
        self.currency_combo.setMaximumWidth(160)
        self.currency_label = QLabel("Para Birimi", objectName="FieldLabel")
        editor_layout.addRow(self.currency_label, self.currency_combo)

        self.amount_row_wrap = QWidget(self)
        row2 = QHBoxLayout(self.amount_row_wrap)
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(10)
        self.amount_stack = QStackedWidget(self.amount_row_wrap)
        self.amount_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.amount_input = CurrencyAmountInput(self, decimals=2, currency="TRY", placeholder="Varsayılan tutar")
        self.amount_input.setPlaceholderText("Varsayılan tutar")
        self.amount_input.setMinimumHeight(50)
        self.amount_stack.addWidget(self.amount_input)

        self.amount_percentage_host = QWidget(self)
        amount_percentage_row = QHBoxLayout(self.amount_percentage_host)
        amount_percentage_row.setContentsMargins(0, 0, 0, 0)
        amount_percentage_row.setSpacing(0)
        self.amount_percentage_input = CircularPercentageInput(self, decimals=2, diameter=118)
        self.amount_percentage_input.setPlaceholderText("%")
        amount_percentage_row.addWidget(
            self.amount_percentage_input,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        amount_percentage_row.addStretch(1)
        self.amount_stack.addWidget(self.amount_percentage_host)
        row2.addWidget(self.amount_stack, 1)
        self.amount_label = QLabel("Varsayılan Fiyat", objectName="FieldLabel")
        editor_layout.addRow(self.amount_label, self.amount_row_wrap)
        self.currency_combo.currentIndexChanged.connect(self._sync_cost_currency_badge)

        self.amount_mode_row_wrap = QWidget(self)
        toggle_row = QHBoxLayout(self.amount_mode_row_wrap)
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(8)
        self.amount_mode_net_label = QLabel("KDV Hariç", objectName="StatusInfo")
        self.amount_mode_net_label.setMinimumWidth(0)
        self.amount_mode_net_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        toggle_row.addWidget(self.amount_mode_net_label, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.amount_mode_switch = SwitchButton(self)
        self.amount_mode_switch.setChecked(True)
        self.amount_mode_switch.toggled.connect(self._sync_vat_rate_visibility)
        toggle_row.addWidget(self.amount_mode_switch, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.amount_mode_gross_label = QLabel("KDV Dahil", objectName="StatusInfo")
        self.amount_mode_gross_label.setMinimumWidth(0)
        self.amount_mode_gross_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        toggle_row.addWidget(self.amount_mode_gross_label, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        toggle_row.addStretch(1)
        self.amount_mode_field_label = QLabel("Fiyat KDV", objectName="FieldLabel")
        editor_layout.addRow(self.amount_mode_field_label, self.amount_mode_row_wrap)

        self.vat_rate_label = QLabel("KDV Oranı", objectName="FieldLabel")
        self.vat_rate_host = QWidget(self)
        vat_rate_row = QHBoxLayout(self.vat_rate_host)
        vat_rate_row.setContentsMargins(0, 0, 0, 0)
        vat_rate_row.setSpacing(0)
        self.vat_rate_input = CircularPercentageInput(self, decimals=2, diameter=118)
        self.vat_rate_input.setPlaceholderText("KDV")
        vat_rate_row.addWidget(self.vat_rate_input, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        vat_rate_row.addStretch(1)
        self.vat_rate_host.setMinimumHeight(118)
        self.vat_rate_label.setMinimumHeight(118)
        self.vat_rate_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        editor_layout.addRow(self.vat_rate_label, self.vat_rate_host)
        self.calc_combo.currentIndexChanged.connect(self._sync_cost_amount_visibility)

        self.platforms_combo = SwitchSelectWidget(
            self,
            multi=True,
            include_all=False,
            empty_text="Seçiniz",
            allow_empty=False,
        )
        self.platforms_combo.setPlaceholderText("Platform ara/seç")
        self.platforms_combo.setMinimumHeight(42)
        for label, key in finance_cost_item_platform_options(include_all=False):
            self.platforms_combo.addItem(label, key)
        self.platforms_label = QLabel("Platformlar", objectName="FieldLabel")
        editor_layout.addRow(self.platforms_label, self.platforms_combo)

        self.supported_sources_combo = SwitchSelectWidget(
            self,
            multi=True,
            include_all=False,
            empty_text="Seçiniz",
            allow_empty=True,
        )
        self.supported_sources_combo.setPlaceholderText("Kaynak tipi ara/seç")
        self.supported_sources_combo.setMinimumHeight(42)
        self.supported_sources_combo.selectionChanged.connect(self._sync_source_type_controls)
        self.supported_sources_label = QLabel("İzinli Kaynaklar", objectName="FieldLabel")
        editor_layout.addRow(self.supported_sources_label, self.supported_sources_combo)

        self.default_source_combo = SwitchSelectWidget(
            self,
            multi=False,
            include_all=False,
            empty_text="Seçiniz",
        )
        self.default_source_combo.setPlaceholderText("Varsayılan kaynak")
        self.default_source_combo.setMinimumHeight(42)
        self.default_source_combo.currentIndexChanged.connect(self._sync_source_type_hint)
        self.default_source_label = QLabel("Varsayılan Kaynak", objectName="FieldLabel")
        editor_layout.addRow(self.default_source_label, self.default_source_combo)

        self.source_types_hint_wrap = QFrame(self)
        self.source_types_hint_wrap.setObjectName("QuickCard")
        source_hint_layout = QVBoxLayout(self.source_types_hint_wrap)
        source_hint_layout.setContentsMargins(12, 10, 12, 10)
        source_hint_layout.setSpacing(4)
        self.source_types_hint_title = QLabel("Kaynak akışı özeti", objectName="SectionTitle")
        source_hint_layout.addWidget(self.source_types_hint_title)
        self.source_types_hint = QLabel("", objectName="StatusInfo")
        self.source_types_hint.setWordWrap(True)
        self.source_types_hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.source_types_hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.source_types_hint.setMinimumHeight(54)
        source_hint_layout.addWidget(self.source_types_hint)
        self.source_types_hint_wrap.hide()
        editor_layout.addRow(self.source_types_hint_wrap)

        status_wrap = QWidget(self)
        status_row = QHBoxLayout(status_wrap)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(10)
        self.active_switch = SwitchButton(self)
        self.active_switch.setChecked(True)
        self.active_status_label = QLabel("Aktif", objectName="StatusInfo")
        self.active_status_label.setMinimumWidth(56)
        self.active_switch.clicked.connect(self._sync_active_status_label)
        status_row.addWidget(self.active_switch, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.active_status_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        status_row.addStretch(1)
        editor_layout.addRow(QLabel("Durum", objectName="FieldLabel"), status_wrap)

        self._workspace.set_editor_widget(editor_host)

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text="Formu Temizle",
            save_new_text="Maliyet Kartını Kaydet",
            save_edit_text="Güncelle",
            delete_text="Sil",
        )
        self.btn_new_cost = self._workspace.editor_action_bar.clear_button
        self.btn_save_cost = self._workspace.editor_action_bar.save_button
        self.btn_delete_cost = self._workspace.editor_action_bar.delete_button
        self._workspace.editor_action_bar.clearRequested.connect(self._new_item)
        self._workspace.editor_action_bar.saveRequested.connect(self._save_item)
        self._workspace.editor_action_bar.deleteRequested.connect(self._delete_active_item)

        bulk_content = QWidget(self.bulk_panel)
        bulk_layout = QVBoxLayout(bulk_content)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.setSpacing(8)
        bulk_layout.addWidget(QLabel("Toplu İşlemler", objectName="SectionTitle"))
        self.bulk_summary_label = QLabel("Seçili kart: 0", objectName="StatusInfo")
        bulk_layout.addWidget(self.bulk_summary_label)
        bulk_hint = QLabel("SEÇ ile işaretlediğin maliyet kartları üzerinde toplu işlem yap.", objectName="Muted")
        bulk_hint.setWordWrap(True)
        bulk_layout.addWidget(bulk_hint)
        self.btn_select_all = QPushButton("Tümünü Seç", self)
        self.btn_select_all.setObjectName("Ghost")
        self.btn_select_all.setMinimumHeight(42)
        self.btn_clear_selection = QPushButton("Seçimi Kaldır", self)
        self.btn_clear_selection.setObjectName("Ghost")
        self.btn_clear_selection.setMinimumHeight(42)
        self.btn_accept_selected = QPushButton("Önerilenleri Toplu Kabul Et", self)
        self.btn_accept_selected.setObjectName("Secondary")
        self.btn_accept_selected.setMinimumHeight(42)
        self.btn_delete_selected = QPushButton("Seçilileri Sil", self)
        self.btn_delete_selected.setObjectName("Danger")
        self.btn_delete_selected.setMinimumHeight(42)
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_clear_selection.clicked.connect(self._clear_selection)
        self.btn_accept_selected.clicked.connect(self._accept_pending_cost_items_bulk)
        self.btn_delete_selected.clicked.connect(self._delete_selected_items)
        bulk_layout.addWidget(self.btn_select_all)
        bulk_layout.addWidget(self.btn_clear_selection)
        bulk_layout.addWidget(self.btn_accept_selected)
        bulk_layout.addWidget(self.btn_delete_selected)
        bulk_layout.addStretch(1)
        self._workspace.set_bulk_widget(bulk_content)

        filters_host = QWidget(self)
        filter_layout = QVBoxLayout(filters_host)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(10)

        filter_head = QHBoxLayout()
        filter_head.addStretch(1)
        filter_layout.addLayout(filter_head)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(10)
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("Input")
        self.search_input.setPlaceholderText("Genel Ara (ad, açıklama, hesaplama...)")
        self.search_input.textChanged.connect(self._schedule_reload)
        search_row.addWidget(self.search_input, 1)

        self.btn_reset_filters = QPushButton("Filtreyi Sıfırla", self)
        self.btn_reset_filters.setObjectName("SoftDanger")
        self.btn_reset_filters.clicked.connect(self._reset_filters)
        search_row.addWidget(self.btn_reset_filters, 0, alignment=Qt.AlignmentFlag.AlignRight)
        filter_layout.addLayout(search_row)

        filter_row = QHBoxLayout()
        self.filter_calc_combo = SwitchSelectWidget(
            self,
            title="Değer Tipi",
            all_text="Tümü",
            multi=False,
            include_all=True,
            default_all=True,
        )
        for label, key in finance_cost_calculation_options():
            self.filter_calc_combo.addItem(label, key)
        self.filter_calc_combo.setMinimumWidth(240)
        self.filter_calc_combo.currentIndexChanged.connect(self.request_reload_items)
        filter_row.addWidget(self.filter_calc_combo, 1)

        self.filter_active_combo = SwitchSelectWidget(
            self,
            title="Durum",
            all_text="Tümü",
            multi=False,
            include_all=True,
            default_all=True,
        )
        self.filter_active_combo.addItem("Tümü", "")
        self.filter_active_combo.addItem("Aktif", "Aktif")
        self.filter_active_combo.addItem("Pasif", "Pasif")
        self.filter_active_combo.setMinimumWidth(220)
        self.filter_active_combo.currentIndexChanged.connect(self.request_reload_items)
        filter_row.addWidget(self.filter_active_combo, 1)
        self.filter_source_combo = SwitchSelectWidget(
            self,
            title="Kaynak",
            all_text="Tümü",
            multi=False,
            include_all=True,
            default_all=True,
        )
        self.filter_source_combo.addItem("Tümü", "")
        self.filter_source_combo.addItem("Önerilen", "pending")
        self.filter_source_combo.addItem("Kayıtlı", "saved")
        self.filter_source_combo.setMinimumWidth(220)
        self.filter_source_combo.currentIndexChanged.connect(self.request_reload_items)
        filter_row.addWidget(self.filter_source_combo, 1)
        filter_row.addStretch(1)
        filter_layout.addLayout(filter_row)

        self.filter_summary_label = QLabel("Toplam kart: 0", objectName="StatusInfo")
        filter_layout.addWidget(self.filter_summary_label)
        self._workspace.set_filters_widget(filters_host)

        self.list_widget = FinanceCostItemsListWidget(
            self._workspace.records_card.body_host,
            empty_placeholder_text="Gösterilecek maliyet kartı bulunamadı.",
        )
        self.list_widget.selection_changed.connect(self._on_card_selection_changed)
        self.list_widget.page_changed.connect(lambda *_args: self._update_pagination_ui())
        self._workspace.set_list_widget(self.list_widget)
        self.btn_bulk_select_toggle = self._workspace.footer_bar.select_toggle
        self._workspace.set_records_summary_text("0 / 0 kayıt")
        self._workspace.set_filters_footer_text("Toplam kart: 0")
        self._workspace_shell.close_left_panel()

        self._workspace_adapter = FinanceCostItemsWorkspaceAdapter(self)
        self._workspace_controller = self._workspace.create_behavior_controller(adapter=self._workspace_adapter)
        self._set_left_mode("edit")
        self._load_editor_payload(None)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._has_loaded_once:
            self._set_list_loading(True)
            QTimer.singleShot(0, self.request_reload_items)
            self._close_left_panel()  # Ensures the splitter is forced closed
            self._has_loaded_once = True

    def closeEvent(self, event) -> None:
        worker = self._reload_worker
        if worker is not None and worker.isRunning():
            worker.quit()
            worker.wait(1500)
        super().closeEvent(event)

    def _schedule_reload(self) -> None:
        self._current_page = 1
        self._search_timer.start()

    @staticmethod
    def _card_record_key(record: OrdersStyleCardRecord | None) -> int:
        try:
            if record is None or getattr(record, "payload", None) is None:
                return 0
            return int((record.payload or {}).get("pk") or 0)
        except Exception:
            return 0

    @staticmethod
    def _is_pending_builtin_cost_item(record: dict[str, object] | None) -> bool:
        payload = dict(record or {})
        return bool(payload.get("isBuiltin")) and not bool(payload.get("isBuiltinAccepted"))

    def _build_card_record(self, record: dict[str, object]) -> OrdersStyleCardRecord:
        default_amount_text = finance_cost_amount_display(record)
        default_amount_label = str(record.get("defaultAmountLabel") or "Varsayılan")
        subtitle = (
            f"Değer Tipi: {record.get('valueTypeLabel', '-')} | "
            f"Varsayılan Kaynak: {record.get('defaultSourceTypeLabel', '-')} | "
            f"{default_amount_label}: {default_amount_text}"
        )
        amount_mode_text = str(record.get("amountModeText") or "KDV dahil")
        vat_suffix = f" (%{record.get('vatRateText')})" if record.get("vatRateText") else ""
        extra_parts: list[str] = []
        amount_mode_part = f"{amount_mode_text}{vat_suffix}".strip()
        if amount_mode_part:
            extra_parts.append(amount_mode_part)
        extra_parts.append(f"Para Birimi: {finance_cost_currency(record)}")
        supported_platforms_text = str(record.get("supportedPlatformsText") or "").strip()
        if supported_platforms_text:
            extra_parts.append(f"Platformlar: {supported_platforms_text}")
        source_types_text = str(record.get("supportedSourceTypesText") or "").strip()
        if source_types_text:
            extra_parts.append(f"Kaynaklar: {source_types_text}")
        system_rule_label = str(record.get("systemRuleLabel") or "").strip()
        if system_rule_label:
            extra_parts.append(f"Sistem Kuralı: {system_rule_label}")
        if self._is_pending_builtin_cost_item(record):
            extra_parts.append(FINANCE_COST_ITEM_PENDING_BADGE_TEXT)
        extra_parts.append(f"Durum: {'Aktif' if record.get('isActive') else 'Pasif'}")
        description = str(record.get("description") or "").strip()
        extra = " | ".join(extra_parts)
        if description:
            extra = f"{description} | {extra}"
        return OrdersStyleCardRecord(
            orderNumber=str(record.get("pk") or ""),
            title=str(record.get("name") or "-"),
            subtitle=subtitle,
            extra=extra,
            logo_path=os.path.join(ASSETS_DIR, "finance-cost-items-icon.png"),
            payload=record,
            _selected=int(record.get("pk") or 0) in self._selected_pks,
        )

    def _refresh_left_panel_header(self) -> None:
        title = "Düzenle"
        subtitle = "Düzenlemek için sağdaki listeden bir maliyet kartı seç."
        if self._left_mode == "new":
            title = "Yeni Ekle"
            subtitle = "Yeni maliyet kartını doldurup kaydet."
        elif self._left_mode == "bulk":
            title = "Toplu Seçim"
            subtitle = "SEÇ ile işaretlediğin maliyet kalemleri için toplu işlem yap."
        elif self._active_pk > 0 and self._active_pk in self._record_map:
            subtitle = f"Seçili kart: {str(self._record_map[self._active_pk].get('name') or '-')}"
        self.left_panel_title.setText(title)
        self.left_panel_hint.setText(subtitle)
        self._workspace.set_left_title(title)
        self._workspace.set_left_subtitle(subtitle)

    def _set_left_mode(self, mode: str) -> None:
        mode_key = str(mode or "").strip().lower()
        if mode_key not in {"new", "edit", "bulk"}:
            mode_key = "edit"
        self._left_mode = mode_key
        self._workspace.set_editor_action_mode(mode_key)
        show_editor = mode_key in {"new", "edit"}
        self.editor_scroll.setVisible(show_editor)
        self.editor_actions_wrap.setVisible(show_editor)
        self.bulk_panel.setVisible(not show_editor)
        self._workspace.set_editor_action_delete_available(
            show_editor and mode_key == "edit" and self._active_pk > 0 and not self._is_builtin_cost_item()
        )
        self._refresh_left_panel_header()
        self._workspace.schedule_editor_layout_refresh()

    def _splitter_total_size(self) -> int:
        return self._workspace_shell.splitter_total_size()

    def _is_left_panel_open(self) -> bool:
        return self._workspace_shell.is_left_panel_open()

    def _open_left_panel(self) -> None:
        self._workspace_shell.open_left_panel(min_left=380, min_right=280)

    def _close_left_panel(self) -> None:
        self._workspace_shell.close_left_panel()

    def _sync_sidebar_state_from_splitter(self) -> None:
        controller = getattr(self, "_workspace_controller", None)
        if controller is not None:
            controller.sync_state()

    def _current_left_guidance_message(self) -> str:
        panel_open = self._is_left_panel_open()
        if panel_open and self._left_mode == "edit" and self._active_pk <= 0:
            return "Düzenlemek için sağdaki listeden bir maliyet kartı seç."
        if panel_open and self._left_mode == "bulk" and not bool(self._selected_pks):
            return "Toplu işlem için sağdaki listeden en az bir kartı SEÇ ile işaretle."
        return ""

    def _tick_active_card_animation(self) -> None:
        self.list_widget.sync_dynamic_row_width()

    def _on_panel_sidebar_toggled(self, panel_id: str, active: bool) -> None:
        if not active:
            self._close_left_panel()
            return
        if panel_id == "new":
            self._new_item(open_panel=False)
        elif panel_id == "bulk":
            self._set_left_mode("bulk")
        else:
            self._set_left_mode("edit")
            if self._active_pk <= 0:
                self._load_editor_payload(None)
        self._open_left_panel()

    def _load_editor_payload(self, record: dict | None) -> None:
        rec = dict(record or {})
        self.cost_name_input.setText(str(rec.get("name") or ""))
        self.cost_description_input.setPlainText(str(rec.get("description") or ""))
        self._set_combo_value(self.calc_combo, str(rec.get("valueType") or "numeric"))
        self._set_numeric_value(self.amount_input, rec.get("defaultAmount"))
        self._set_numeric_value(self.amount_percentage_input, rec.get("defaultAmount"))
        self._set_combo_value(self.currency_combo, finance_cost_currency(rec))
        self.amount_mode_switch.setChecked(bool(rec.get("isVatIncluded", True)))
        self._set_numeric_value(self.vat_rate_input, rec.get("vatRate"))
        self.active_switch.setChecked(bool(rec.get("isActive", True)))
        self._set_multi_combo_data(
            self.platforms_combo,
            [str(value) for value in list(rec.get("supportedPlatformSourceIds") or []) if str(value).strip()],
        )
        self._sync_active_status_label()
        self._sync_cost_amount_visibility()
        self._sync_vat_rate_visibility()
        self._populate_source_type_widgets(
            record=rec,
            supported_types=list(rec.get("supportedSourceTypes") or ["manual_value"]),
            default_source_type=str(rec.get("defaultSourceType") or "manual_value"),
        )
        self._apply_cost_item_edit_policy(rec)
        self._refresh_left_panel_header()

    def _is_builtin_cost_item(self, record: dict | None = None) -> bool:
        payload = dict(record or (self._record_map.get(self._active_pk) or {}))
        return bool(payload.get("isBuiltin"))

    def _selected_has_builtin_cost_items(self) -> bool:
        return any(bool((self._record_map.get(pk) or {}).get("isBuiltin")) for pk in self._selected_pks)

    @staticmethod
    def _builtin_editable_fields(record: dict | None) -> set[str]:
        payload = dict(record or {})
        values = {
            str(value or "").strip()
            for value in list(payload.get("editableFields") or [])
            if str(value or "").strip()
        }
        return values or {"name", "description"}

    def _apply_cost_item_edit_policy(self, record: dict | None) -> None:
        is_builtin = self._is_builtin_cost_item(record)
        is_percentage = str(self.calc_combo.currentData() or "").strip().lower() == "percentage"
        editable_fields = self._builtin_editable_fields(record) if is_builtin else set()
        for widget in (
            self.calc_combo,
            self.currency_combo,
            self.amount_input,
            self.amount_percentage_input,
            self.amount_mode_switch,
            self.vat_rate_input,
            self.active_switch,
            self.platforms_combo,
        ):
            if hasattr(widget, "setLockOnDisabled"):
                try:
                    widget.setLockOnDisabled(True)
                except Exception:
                    pass
        self.cost_name_input.setEnabled(not is_builtin or "name" in editable_fields)
        self.cost_description_input.setEnabled(not is_builtin or "description" in editable_fields)
        self.calc_combo.setEnabled(not is_builtin or "valueType" in editable_fields)
        self.currency_combo.setEnabled((not is_builtin or "currency" in editable_fields) and not is_percentage)
        self.amount_input.setEnabled((not is_builtin or "defaultAmount" in editable_fields) and not is_percentage)
        self.amount_percentage_input.setEnabled((not is_builtin or "defaultAmount" in editable_fields) and is_percentage)
        self.amount_mode_switch.setEnabled(not is_builtin or "isVatIncluded" in editable_fields)
        self.vat_rate_input.setEnabled(not is_builtin or "vatRate" in editable_fields)
        self.active_switch.setEnabled(not is_builtin or "isActive" in editable_fields)
        self.platforms_combo.setEnabled(not is_builtin or "supportedPlatforms" in editable_fields)
        self._workspace.set_editor_action_delete_available(
            self._active_pk > 0 and self._left_mode == "edit" and not is_builtin
        )

    def _set_combo_value(self, combo, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _set_combo_text(self, combo, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            combo.setSelectedTexts([])
            return
        idx = combo.findText(text)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            return
        combo.setSelectedTexts([])

    def _set_multi_combo_data(self, combo, values: list[str] | None) -> None:
        target_values = {str(value or "").strip() for value in list(values or []) if str(value or "").strip()}
        selected_texts: list[str] = []
        items = list(getattr(combo, "_items", []) or [])
        for entry in items:
            data = entry.get("data")
            if str(data or "").strip() in target_values:
                selected_texts.append(str(entry.get("text") or ""))
        combo.setSelectedTexts(selected_texts)

    def _set_numeric_value(self, widget: QWidget, value: object) -> None:
        if hasattr(widget, "setValue"):
            try:
                widget.setValue(None if value in (None, "") else float(value))
                return
            except Exception:
                pass
        if hasattr(widget, "setText"):
            widget.setText("" if value in (None, "") else str(value))

    @staticmethod
    def _record_system_rule_key(record: dict | None) -> str:
        payload = dict(record or {})
        if str(payload.get("defaultSourceType") or "").strip().lower() != "builtin_resolver":
            return ""
        config = dict(payload.get("defaultSourceConfig") or {}) or {}
        return str(config.get("ruleKey") or "").strip()

    def _cost_source_options_for_record(self, record: dict | None = None) -> list[tuple[str, str]]:
        rec = dict(record or {})
        if self._record_system_rule_key(rec):
            options = ["builtin_resolver"]
        else:
            options = ["manual_value"]
        return [(cost_source_type_label(key), key) for key in options]

    def _populate_source_type_widgets(
        self,
        *,
        record: dict | None = None,
        supported_types: list[str] | None = None,
        default_source_type: str | None = None,
    ) -> None:
        options = self._cost_source_options_for_record(record)
        option_keys = [key for _, key in options]

        selected_supported: list[str] = []
        for raw in list(supported_types or []):
            key = normalize_cost_source_type(raw, fallback="")
            if key and key in option_keys and key not in selected_supported:
                selected_supported.append(key)
        if not selected_supported:
            selected_supported = option_keys[:1]

        default_key = normalize_cost_source_type(default_source_type, fallback="")
        if default_key not in selected_supported:
            default_key = selected_supported[0] if selected_supported else ""

        with QSignalBlocker(self.supported_sources_combo):
            self.supported_sources_combo.clear()
            for label, key in options:
                self.supported_sources_combo.addItem(label, key, checked=key in selected_supported)

        with QSignalBlocker(self.default_source_combo):
            self.default_source_combo.clear()
            for label, key in options:
                if key in selected_supported:
                    self.default_source_combo.addItem(label, key)
            idx = self.default_source_combo.findData(default_key)
            self.default_source_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.default_source_combo.setEnabled(False)
        self._sync_source_type_hint()
        self.supported_sources_label.setVisible(False)
        self.default_source_label.setVisible(False)
        self.supported_sources_combo.setVisible(False)
        self.default_source_combo.setVisible(False)
        self.source_types_hint_wrap.setVisible(True)
        self.supported_sources_combo.setEnabled(False)
        self.default_source_combo.setEnabled(False)

    def _sync_source_type_controls(self, *_args) -> None:
        self._sync_source_type_hint()

    def _sync_source_type_hint(self, *_args) -> None:
        active = dict(self._record_map.get(self._active_pk, {}))
        system_rule_key = self._record_system_rule_key(active)
        if system_rule_key:
            self.source_types_hint_title.setText("Sistem Kuralı")
            self.source_types_hint.setText(
                f"Bu kartın kuralı sistem tarafından tanımlıdır: {finance_cost_rule_label(system_rule_key)}.\n"
                "Kural tabanlı kaynak seçimi kullanıcı tarafından değiştirilemez."
            )
            return
        self.source_types_hint_title.setText("Kaynak Tipi")
        self.source_types_hint.setText(
            "Kullanıcı tarafından oluşturulan maliyet kartları manuel değerle çalışır.\n"
            "Kural tabanlı kaynaklar yalnızca sistemin tanımladığı varsayılan kartlarda kullanılır."
        )

    def _sync_cost_amount_visibility(self, *_args) -> None:
        value_type = str(self.calc_combo.currentData() or "").strip().lower()
        is_percentage = value_type == "percentage"
        self.amount_label.setText("Varsayılan Oran" if is_percentage else "Varsayılan Fiyat")
        self.amount_input.setPlaceholderText("Varsayılan tutar")
        self.amount_stack.setCurrentWidget(self.amount_percentage_host if is_percentage else self.amount_input)
        self.amount_stack.setFixedHeight(126 if is_percentage else 58)
        self.currency_label.setVisible(not is_percentage)
        self.currency_combo.setVisible(not is_percentage)
        self.amount_label.setMinimumHeight(118 if is_percentage else 58)
        self.amount_label.setMaximumHeight(118 if is_percentage else 58)
        self.amount_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.amount_row_wrap.setMinimumHeight(126 if is_percentage else 58)
        self.amount_row_wrap.setMaximumHeight(126 if is_percentage else 58)
        self.amount_label.setVisible(True)
        self.amount_row_wrap.setVisible(True)
        self.amount_mode_field_label.setVisible(True)
        self.amount_mode_row_wrap.setVisible(True)
        self._sync_vat_rate_visibility()
        self._sync_cost_currency_badge()
        self._apply_cost_item_edit_policy(self._record_map.get(self._active_pk))

    def _sync_cost_currency_badge(self, *_args) -> None:
        value_type = str(self.calc_combo.currentData() or "").strip().lower()
        if value_type == "percentage":
            return
        self.amount_input.setCurrency(str(self.currency_combo.currentData() or "TRY"))

    def _sync_vat_rate_visibility(self, *_args) -> None:
        is_vat_included = self.amount_mode_switch.isChecked()
        self.amount_mode_gross_label.setStyleSheet(
            "color: #15803d; font-weight: 800;" if is_vat_included else "color: #64748b; font-weight: 600;"
        )
        self.amount_mode_net_label.setStyleSheet(
            "color: #b45309; font-weight: 800;" if not is_vat_included else "color: #64748b; font-weight: 600;"
        )
        self.vat_rate_label.setVisible(True)
        self.vat_rate_host.setVisible(True)

    def _set_active_card_animation_enabled(self, enabled: bool) -> None:
        self.list_widget.set_active_spin_allowed(bool(enabled))
        self._active_card_timer.stop()

    def _collect_payload(self) -> dict[str, object]:
        active = self._record_map.get(self._active_pk, {})
        supported_platform_source_ids = [
            int(str(value).strip())
            for value in list(self.platforms_combo.selectedData() or [])
            if str(value or "").strip()
        ]
        system_rule_key = self._record_system_rule_key(active)
        if system_rule_key:
            supported_source_types = list(active.get("supportedSourceTypes") or ["manual_value", "builtin_resolver"])
            default_source_type = "builtin_resolver"
            default_source_config = dict(active.get("defaultSourceConfig") or {"ruleKey": system_rule_key})
        else:
            supported_source_types = ["manual_value"]
            default_source_type = "manual_value"
            default_source_config = None
        return {
            "pk": active.get("pk"),
            "costKey": active.get("costKey"),
            "name": self.cost_name_input.text().strip(),
            "description": self.cost_description_input.toPlainText().strip(),
            "valueType": str(self.calc_combo.currentData() or ""),
            "defaultMatchMode": active.get("defaultMatchMode"),
            "defaultAmount": (
                self.amount_percentage_input.text().strip()
                if str(self.calc_combo.currentData() or "").strip().lower() == "percentage"
                else self.amount_input.text().strip()
            ),
            "currency": str(self.currency_combo.currentData() or "TRY"),
            "isVatIncluded": self.amount_mode_switch.isChecked(),
            "vatRate": self.vat_rate_input.text().strip(),
            "supportedPlatformSourceIds": supported_platform_source_ids,
            "supportedSourceTypes": supported_source_types,
            "defaultSourceType": default_source_type,
            "defaultSourceConfig": default_source_config,
            "isActive": self.active_switch.isChecked(),
        }

    def _new_item(self, *, open_panel: bool = True) -> None:
        self._active_pk = 0
        self._set_left_mode("new")
        self._load_editor_payload(
            {
                "name": "",
                "description": "",
                "valueType": "numeric",
                "defaultAmount": "",
                "currency": "TRY",
                "isVatIncluded": True,
                "vatRate": "",
                "supportedPlatformSourceIds": [1],
                "supportedSourceTypes": ["manual_value"],
                "defaultSourceType": "manual_value",
                "isActive": True,
            }
        )
        self._sync_card_states()
        if open_panel:
            self._open_left_panel()

    def _save_item(self) -> None:
        result = save_finance_cost_item(self._collect_payload())
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        saved = (result.data or {}).get("record") or {}
        self._search_timer.stop()
        self._set_left_mode("edit")
        self.reload_items(active_pk=int(saved.get("pk") or 0))
        MessageHandler.show(self, result, only_errors=False)
        self.itemsChanged.emit()

    def _delete_active_item(self) -> None:
        if self._active_pk <= 0:
            return
        result = delete_finance_cost_item(self._active_pk)
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        self._selected_pks.discard(self._active_pk)
        self._active_pk = 0
        self.reload_items()
        self.itemsChanged.emit()

    def _delete_selected_items(self) -> None:
        if not self._selected_pks:
            return
        result = delete_finance_cost_items(sorted(self._selected_pks))
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        self._selected_pks.clear()
        self._active_pk = 0
        self.reload_items()
        self.itemsChanged.emit()

    def _select_all(self) -> None:
        self._selected_pks = {
            int(row.get("pk") or 0)
            for row in self._records
            if int(row.get("pk") or 0) > 0 and not self._is_pending_builtin_cost_item(row)
        }
        self._sync_card_states()
        self._sync_bulk_summary()

    def _clear_selection(self) -> None:
        self._selected_pks.clear()
        self._sync_card_states()
        self._sync_bulk_summary()

    def _reset_filters(self) -> None:
        self.search_input.clear()
        self.filter_calc_combo.setCurrentIndex(0)
        self.filter_active_combo.setCurrentIndex(0)
        self.filter_source_combo.setCurrentIndex(0)
        self.reload_items()

    def _switch_source_filter_to_saved_if_pending(self) -> None:
        if str(self.filter_source_combo.currentData() or "").strip().lower() != "pending":
            return
        saved_index = self.filter_source_combo.findData("saved")
        if saved_index >= 0:
            self.filter_source_combo.setCurrentIndex(saved_index)

    def _sync_active_status_label(self, *_args) -> None:
        self.active_status_label.setText("Aktif" if self.active_switch.isChecked() else "Pasif")

    def _on_page_size_changed(self) -> None:
        try:
            self._page_size = max(1, int(getattr(self.list_widget, "page_size", 50) or 50))
        except Exception:
            self._page_size = 50
        self._update_pagination_ui()

    def _on_prev_page(self) -> None:
        self.list_widget.prev_page()
        self._current_page = self.list_widget.current_page
        self._update_pagination_ui()

    def _on_next_page(self) -> None:
        self.list_widget.next_page()
        self._current_page = self.list_widget.current_page
        self._update_pagination_ui()

    def _workspace_clear_active_record(self) -> None:
        self._active_pk = 0
        self._load_editor_payload(None)
        self._sync_card_states()

    def _workspace_activate_record(self, record: OrdersStyleCardRecord) -> None:
        self._active_pk = self._card_record_key(record)
        self._set_left_mode("edit")
        self._load_editor_payload(self._record_map.get(self._active_pk))
        self._sync_card_states()

    def _workspace_apply_selection(self, record: OrdersStyleCardRecord, selected: bool) -> None:
        key = self._card_record_key(record)
        if key <= 0:
            return
        record_payload = dict(getattr(record, "payload", None) or {})
        if self._is_pending_builtin_cost_item(record_payload):
            if selected:
                self._accept_builtin_cost_item(key)
            return
        if selected:
            self._selected_pks.add(key)
        else:
            self._selected_pks.discard(key)
        self._sync_bulk_summary()
        self._sync_card_states()

    def _on_workspace_state_changed(self) -> None:
        self._refresh_left_panel_header()
        self._workspace.set_filters_footer_text(self.filter_summary_label.text())
        active_record = next(
            (record for record in (self.list_widget.filtered_records or []) if self._card_record_key(record) == self._active_pk),
            None,
        )
        self._set_active_card_animation_enabled(
            active_record is not None and self._left_mode == "edit" and self._is_left_panel_open()
        )

    def _open_record(self, record_pk: int) -> None:
        clicked_pk = int(record_pk or 0)
        if (
            self._left_mode == "edit"
            and self._is_left_panel_open()
            and self._active_pk > 0
            and self._active_pk == clicked_pk
        ):
            self._active_pk = 0
            self._load_editor_payload(None)
            self._sync_card_states()
            self._close_left_panel()
            return
        self._active_pk = int(record_pk or 0)
        record = self._record_map.get(self._active_pk)
        self._set_left_mode("edit")
        self._load_editor_payload(record)
        self._sync_card_states()
        self._open_left_panel()

    def _sync_bulk_summary(self) -> None:
        self.bulk_summary_label.setText(f"Seçili kart: {len(self._selected_pks)}")
        enabled = bool(self._selected_pks)
        pending_visible = [
            int(row.get("pk") or 0)
            for row in self._records
            if int(row.get("pk") or 0) > 0 and self._is_pending_builtin_cost_item(row)
        ]
        pending_selected = [pk for pk in self._selected_pks if pk in pending_visible]
        self.btn_clear_selection.setEnabled(enabled)
        self.btn_accept_selected.setEnabled(bool(pending_selected or pending_visible))
        self.btn_delete_selected.setEnabled(enabled and not self._selected_has_builtin_cost_items())
        self.btn_bulk_select_toggle.setSelectionCounts(len(self._selected_pks), len(self._records))

    def _sync_card_states(self) -> None:
        for record in self.list_widget.filtered_records or []:
            setattr(record, "_selected", self._card_record_key(record) in self._selected_pks)
        self.list_widget._build_page()
        active_record = next(
            (record for record in (self.list_widget.filtered_records or []) if self._card_record_key(record) == self._active_pk),
            None,
        )
        if active_record is not None:
            self.list_widget.set_active_record(active_record)
        else:
            self.list_widget.clear_active_record()
        self._set_active_card_animation_enabled(
            active_record is not None and self._left_mode == "edit" and self._is_left_panel_open()
        )
        self._update_pagination_ui()

    def _update_pagination_ui(self) -> None:
        total = len(self.list_widget.filtered_records or [])
        try:
            self._page_size = max(1, int(getattr(self.list_widget, "page_size", self._page_size) or self._page_size))
        except Exception:
            pass
        self._workspace.set_records_summary_text(f"{self.list_widget.shown_count()} / {total} kayıt")
        self._workspace.footer_bar.refresh()
        self.btn_bulk_select_toggle.setSelectionCounts(len(self._selected_pks), total)

    def _on_card_record_clicked(self, record: OrdersStyleCardRecord) -> None:
        self._open_record(self._card_record_key(record))

    def _on_card_blank_area_clicked(self) -> None:
        self._active_pk = 0
        self.list_widget.clear_active_record()
        if self._left_mode == "edit":
            self._close_left_panel()
        self._load_editor_payload(None)
        self._refresh_left_panel_header()

    def _on_card_select_button_clicked(self, record: OrdersStyleCardRecord, selected: bool) -> None:
        key = self._card_record_key(record)
        if key <= 0:
            return
        record_payload = dict(getattr(record, "payload", None) or {})
        if self._is_pending_builtin_cost_item(record_payload):
            self._accept_builtin_cost_item(key)
            return
        if selected:
            self._selected_pks.add(key)
        else:
            self._selected_pks.discard(key)
        count = len(self._selected_pks)
        self._sync_bulk_summary()
        self._sync_card_states()
        if count <= 0:
            if self._left_mode == "bulk" and self._is_left_panel_open():
                self._close_left_panel()
            else:
                self._sync_sidebar_state_from_splitter()
            return
        if self._selected_pks:
            self._set_left_mode("bulk")
            self._open_left_panel()

    def _accept_builtin_cost_item(self, item_pk: int) -> None:
        target = dict(self._record_map.get(int(item_pk or 0)) or {})
        if not self._is_pending_builtin_cost_item(target):
            return
        if not AppMessageCenter.confirm(
            self,
            FINANCE_COST_ITEM_ACCEPT_TITLE,
            FINANCE_COST_ITEM_ACCEPT_CONFIRMATION_TEXT,
            default_yes=False,
        ):
            return
        result = accept_finance_cost_item(int(item_pk or 0))
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        self._search_timer.stop()
        self._switch_source_filter_to_saved_if_pending()
        self.reload_items(active_pk=int(item_pk or 0), preserve_page=True)
        MessageHandler.show(self, result, only_errors=False)
        self.itemsChanged.emit()

    def _accept_pending_cost_items_bulk(self) -> None:
        target_pks = [
            pk for pk in self._selected_pks
            if self._is_pending_builtin_cost_item(self._record_map.get(int(pk or 0)))
        ]
        if not target_pks:
            target_pks = [
                int(row.get("pk") or 0)
                for row in self._records
                if int(row.get("pk") or 0) > 0 and self._is_pending_builtin_cost_item(row)
            ]
        if not target_pks:
            return
        if not AppMessageCenter.confirm(
            self,
            "Toplu Kabul",
            f"{len(target_pks)} önerilen maliyet kartını kullanıma almak istiyor musun?",
            default_yes=False,
        ):
            return
        first_error = ""
        for item_pk in target_pks:
            result = accept_finance_cost_item(int(item_pk or 0))
            if not result.success and not first_error:
                first_error = str(result.message or "Bilinmeyen hata")
        self._search_timer.stop()
        self._switch_source_filter_to_saved_if_pending()
        self.reload_items(preserve_page=True)
        if first_error:
            MessageHandler.show(self, Result.fail(first_error, close_dialog=False), only_errors=True)
            return
        MessageHandler.show(self, Result.ok("Önerilen maliyet kartları kullanıma alındı.", close_dialog=False), only_errors=False)
        self.itemsChanged.emit()

    def _on_card_selection_changed(self) -> None:
        self._selected_pks = {
            self._card_record_key(record)
            for record in self.list_widget.get_selected_records()
            if self._card_record_key(record) > 0
        }
        self._sync_bulk_summary()
        self._update_pagination_ui()
        controller = getattr(self, "_workspace_controller", None)
        if controller is not None:
            controller.sync_state()

    def _clear_all_selections(self) -> None:
        self._selected_pks.clear()
        self._sync_bulk_summary()
        self._sync_card_states()
        if self._left_mode == "bulk":
            self._close_left_panel()

    def _on_bulk_toggle_action(self, action: str) -> None:
        if str(action or "") == "clear":
            self._clear_all_selections()
            return
        self._select_all()
        self._set_left_mode("bulk")
        self._open_left_panel()

    def _set_list_loading(self, busy: bool, message: str = "Maliyet kartları yükleniyor...") -> None:
        self._workspace.set_list_loading(bool(busy), message=message)

    def _reload_context(self, *, active_pk: int | None = None, preserve_page: bool = False) -> dict[str, object]:
        return {
            "active_pk": int(active_pk or self._active_pk or 0),
            "preserve_page": bool(preserve_page),
            "current_page": int(self._current_page or 1),
            "params": {
                "search_text": self.search_input.text().strip(),
                "calculation_type": str(self.filter_calc_combo.currentData() or "").strip(),
                "active_state": str(self.filter_active_combo.currentData() or "").strip(),
                "source_state": str(self.filter_source_combo.currentData() or "").strip(),
            },
        }

    def _apply_reload_result(self, result: Result, context: dict[str, object]) -> None:
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return

        data = result.data or {}
        self._records = list(data.get("records") or [])
        if not bool(context.get("preserve_page")):
            self._current_page = 1
        self._record_map = {int(row.get("pk") or 0): row for row in self._records if int(row.get("pk") or 0) > 0}
        self.filter_summary_label.setText(str(data.get("summary_text") or "Toplam maliyet: 0"))
        self._workspace.set_filters_footer_text(self.filter_summary_label.text())
        self._selected_pks = {pk for pk in self._selected_pks if pk in self._record_map}
        self._sync_bulk_summary()
        card_records = [self._build_card_record(record) for record in self._records]
        self.list_widget.set_page_size(self._page_size)
        self.list_widget.set_records(card_records)
        if bool(context.get("preserve_page")):
            self.list_widget.go_to_page(int(context.get("current_page") or self._current_page or 1))
        else:
            self.list_widget.go_to_page(1)
        self._current_page = self.list_widget.current_page

        next_pk = int(context.get("active_pk") or 0)
        if next_pk > 0 and next_pk in self._record_map:
            self._active_pk = next_pk
            self._load_editor_payload(self._record_map.get(self._active_pk))
        else:
            self._active_pk = 0
            self._load_editor_payload(None)
        self._sync_card_states()
        self._sync_sidebar_state_from_splitter()

    def request_reload_items(self, *_args, active_pk: int | None = None, preserve_page: bool = False) -> None:
        worker = self._reload_worker
        if worker is not None and worker.isRunning():
            self._reload_pending = True
            return
        self._reload_pending = False
        self._reload_seq += 1
        seq = int(self._reload_seq)
        context = self._reload_context(active_pk=active_pk, preserve_page=preserve_page)
        self._set_list_loading(True)
        worker = SyncWorker(load_finance_cost_items, parent=self, **dict(context.get("params") or {}))
        self._reload_worker = worker

        def _handle_result(result: Result) -> None:
            if seq == self._reload_seq:
                self._apply_reload_result(result, context)

        def _handle_finished() -> None:
            if self._reload_worker is worker:
                self._reload_worker = None
            worker.deleteLater()
            if seq == self._reload_seq:
                self._set_list_loading(False)
            if self._reload_pending:
                self._reload_pending = False
                QTimer.singleShot(0, self.request_reload_items)

        worker.result_ready.connect(_handle_result)
        worker.finished.connect(_handle_finished)
        worker.start()

    def reload_items(self, *_args, active_pk: int | None = None, preserve_page: bool = False) -> None:
        self._set_list_loading(True)
        try:
            result = load_finance_cost_items(
                search_text=self.search_input.text().strip(),
                calculation_type=str(self.filter_calc_combo.currentData() or "").strip(),
                active_state=str(self.filter_active_combo.currentData() or "").strip(),
                source_state=str(self.filter_source_combo.currentData() or "").strip(),
            )
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                return

            data = result.data or {}
            self._records = list(data.get("records") or [])
            if not preserve_page:
                self._current_page = 1
            self._record_map = {int(row.get("pk") or 0): row for row in self._records if int(row.get("pk") or 0) > 0}
            self.filter_summary_label.setText(str(data.get("summary_text") or "Toplam maliyet: 0"))
            self._workspace.set_filters_footer_text(self.filter_summary_label.text())
            self._selected_pks = {pk for pk in self._selected_pks if pk in self._record_map}
            self._sync_bulk_summary()
            card_records = [self._build_card_record(record) for record in self._records]
            self.list_widget.set_page_size(self._page_size)
            self.list_widget.set_records(card_records)
            if preserve_page:
                self.list_widget.go_to_page(self._current_page)
            else:
                self.list_widget.go_to_page(1)
            self._current_page = self.list_widget.current_page

            next_pk = int(active_pk or self._active_pk or 0)
            if next_pk > 0 and next_pk in self._record_map:
                self._active_pk = next_pk
                self._load_editor_payload(self._record_map.get(self._active_pk))
            else:
                self._active_pk = 0
                self._load_editor_payload(None)
            self._sync_card_states()
            self._sync_sidebar_state_from_splitter()
        finally:
            self._set_list_loading(False)
