
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from PyQt6.QtCore import Qt, QAbstractListModel, QDate, QModelIndex, QSize, QSignalBlocker, QTimer, pyqtSignal, QRect
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
)

from Account.signals.signals import account_signals
from Account.views.company_list_widget import CompanyListWidget
from Core.threads.async_worker import AsyncWorker
from Core.threads.sync_worker import SyncWorker
from Core.views.tab_widgets import DashboardHeroCard
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

from Core.processors.catalog import currency_options
from Logistics.constants import ui_constants as logistics_ui
from Logistics.signals.signals import logistics_signals
from Marketplaces.signals.signals import marketplace_signals
from Finance.constants.ui_constants import (
    FINANCE_CARGO_TARIFF_ACCEPT_BUTTON_TEXT,
    FINANCE_CARGO_TARIFF_ACCEPT_CONFIRMATION_TEXT,
    FINANCE_CARGO_TARIFF_ACCEPT_TITLE,
    FINANCE_CARGO_TARIFF_PENDING_BADGE_TEXT,
    FINANCE_CARGO_TARIFF_SELECT_BUTTON_TEXT,
    FINANCE_CARGO_TARIFF_SELECTED_BUTTON_TEXT,
)

try:
    FINANCE_CURRENCY_OPTIONS = tuple(currency_options())
except Exception:
    FINANCE_CURRENCY_OPTIONS = ("TRY",)


def _logistics_action(name: str):
    from Logistics.views import actions

    return getattr(actions, name)


def accept_logistics_cargo_tariff(*args, **kwargs):
    return _logistics_action("accept_logistics_cargo_tariff")(*args, **kwargs)


def accept_logistics_cargo_tariffs(*args, **kwargs):
    return _logistics_action("accept_logistics_cargo_tariffs")(*args, **kwargs)


def delete_logistics_cargo_tariff(*args, **kwargs):
    return _logistics_action("delete_logistics_cargo_tariff")(*args, **kwargs)


def delete_logistics_cargo_tariffs(*args, **kwargs):
    return _logistics_action("delete_logistics_cargo_tariffs")(*args, **kwargs)


def load_logistics_cargo_tariffs(*args, **kwargs):
    return _logistics_action("load_logistics_cargo_tariffs")(*args, **kwargs)


def logistics_cargo_provider_options(*args, **kwargs):
    return _logistics_action("logistics_cargo_provider_options")(*args, **kwargs)


def logistics_cargo_tariff_platform_options(*args, **kwargs):
    return _logistics_action("logistics_cargo_tariff_platform_options")(*args, **kwargs)


def logistics_cargo_tariff_visible_fields(*args, **kwargs):
    return _logistics_action("logistics_cargo_tariff_visible_fields")(*args, **kwargs)


def save_logistics_cargo_tariff(*args, **kwargs):
    return _logistics_action("save_logistics_cargo_tariff")(*args, **kwargs)


def compact_number_text(value: object) -> str:
    if value in (None, ""):
        return ""
    try:
        numeric = float(str(value).replace(",", "."))
    except Exception:
        return str(value or "").strip()
    text = f"{numeric:.2f}" if abs(numeric - round(numeric)) > 1e-9 else f"{int(round(numeric))}"
    return text.rstrip("0").rstrip(".") if "." in text else text
from Core.views import (
    RECORD_WORKSPACE_STYLE as FINANCE_STYLE,
    RecordWorkspaceCardRecord as OrdersStyleCardRecord,
    RecordWorkspaceListDelegate as OrdersStyleListDelegate,
    RecordWorkspaceListModel as OrdersStyleListModel,
    RecordWorkspaceListWidget as OrdersStyleListWidget,
)


class _NumericRangeInputs(QWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        decimals: int = 2,
        left_placeholder: str = "",
        right_placeholder: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("NumericRangeInputs")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        self._left_edit = NumericPulseLineEdit(self, decimals=decimals)
        self._left_edit.setObjectName("Input")
        self._left_edit.setPlaceholderText(left_placeholder or "")
        self._left_edit.setMinimumHeight(42)
        layout.addWidget(self._left_edit, 1)

        dash = QLabel(logistics_ui.LOGISTICS_RANGE_SEPARATOR_TEXT, self, objectName="StatusInfo")
        dash.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dash.setMinimumWidth(18)
        layout.addWidget(dash, 0)

        self._right_edit = NumericPulseLineEdit(self, decimals=decimals)
        self._right_edit.setObjectName("Input")
        self._right_edit.setPlaceholderText(right_placeholder or "")
        self._right_edit.setMinimumHeight(42)
        layout.addWidget(self._right_edit, 1)

        self.setMinimumHeight(54)

    def setValues(self, left_value: float | None, right_value: float | None) -> None:
        self._left_edit.setValue(left_value)
        self._right_edit.setValue(right_value)

    def leftText(self) -> str:
        return self._left_edit.text()

    def rightText(self) -> str:
        return self._right_edit.text()

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self._left_edit.setEnabled(enabled)
        self._right_edit.setEnabled(enabled)


class _CurrencyRangeInputs(QWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        decimals: int = 2,
        currency: str = "TRY",
        left_placeholder: str = "",
        right_placeholder: str = "",
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._left_input = CurrencyAmountInput(self, decimals=decimals, currency=currency, placeholder=left_placeholder)
        self._left_input.setPlaceholderText(left_placeholder or "")
        self._left_input.setMinimumHeight(50)
        layout.addWidget(self._left_input, 1)

        dash = QLabel(logistics_ui.LOGISTICS_RANGE_SEPARATOR_TEXT, self, objectName="StatusInfo")
        dash.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dash.setMinimumWidth(18)
        layout.addWidget(dash, 0)

        self._right_input = CurrencyAmountInput(self, decimals=decimals, currency=currency, placeholder=right_placeholder)
        self._right_input.setPlaceholderText(right_placeholder or "")
        self._right_input.setMinimumHeight(50)
        layout.addWidget(self._right_input, 1)

    def setValues(self, left_value: float | None, right_value: float | None) -> None:
        self._left_input.setValue(left_value)
        self._right_input.setValue(right_value)

    def leftText(self) -> str:
        return self._left_input.text()

    def rightText(self) -> str:
        return self._right_input.text()

    def setCurrency(self, currency: str) -> None:
        self._left_input.setCurrency(currency)
        self._right_input.setCurrency(currency)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self._left_input.setEnabled(enabled)
        self._right_input.setEnabled(enabled)


class LogisticsCargoTariffsListDelegate(OrdersStyleListDelegate):
    @staticmethod
    def _payload_for(index) -> dict[str, Any]:
        record = index.data(OrdersStyleListModel.RecordRole)
        payload = getattr(record, "payload", None)
        return dict(payload or {}) if isinstance(payload, dict) else {}

    def _is_pending_builtin_index(self, index) -> bool:
        payload = self._payload_for(index)
        return bool(payload.get("isBuiltin")) and not bool(payload.get("isBuiltinAccepted"))

    def _is_seed_removed_builtin_index(self, index) -> bool:
        payload = self._payload_for(index)
        return bool(payload.get("isSeedRemoved"))

    def _hook_text(self, index) -> str:
        if self._is_pending_builtin_index(index):
            return FINANCE_CARGO_TARIFF_ACCEPT_BUTTON_TEXT
        if self._is_seed_removed_builtin_index(index):
            return logistics_ui.LOGISTICS_TARIFFS_DELETE_SEED_TEXT
        return super()._hook_text(index)

    def _hook_rect_for_index(self, rect: QRect, index, view=None):
        if self._is_pending_builtin_index(index) or self._is_seed_removed_builtin_index(index):
            return self._build_hook_rect(
                rect,
                view=view,
                hook_w=self._hook_width_for_index(index, minimum=88),
                hook_h=34,
            )
        return super()._hook_rect_for_index(rect, index, view)


class LogisticsCargoTariffsListWidget(OrdersStyleListWidget):
    def __init__(self, parent=None, *, empty_placeholder_text: str):
        super().__init__(parent, empty_placeholder_text=empty_placeholder_text)
        self._delegate = LogisticsCargoTariffsListDelegate(self, on_select_button=self._on_select_button_clicked)
        self.setItemDelegate(self._delegate)


class LogisticsCargoTariffCard(QFrame):
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

        title = QLabel(str(self.record.get("name") or logistics_ui.LOGISTICS_EMPTY_VALUE_TEXT), objectName="InvoiceTitle")
        title.setWordWrap(True)
        text_col.addWidget(title)

        desc = QLabel(str(self.record.get("description") or logistics_ui.LOGISTICS_TARIFFS_DESCRIPTION_EMPTY_TEXT), objectName="InvoiceMeta")
        desc.setWordWrap(True)
        text_col.addWidget(desc)

        meta = QLabel(
            logistics_ui.LOGISTICS_TARIFFS_META_PLATFORM_TEMPLATE.format(
                platform=self.record.get("platform") or logistics_ui.LOGISTICS_EMPTY_VALUE_TEXT,
                provider=self.record.get("providerText") or logistics_ui.LOGISTICS_EMPTY_VALUE_TEXT,
            ),
            objectName="InvoiceMetaStrong",
        )
        meta.setWordWrap(True)
        text_col.addWidget(meta)

        ranges = QLabel(
            logistics_ui.LOGISTICS_TARIFFS_META_RANGES_TEMPLATE.format(
                desi=self.record.get("desiRangeText") or logistics_ui.LOGISTICS_EMPTY_VALUE_TEXT,
                price=self.record.get("salePriceRangeText") or logistics_ui.LOGISTICS_EMPTY_VALUE_TEXT,
            ),
            objectName="InvoiceMeta",
        )
        ranges.setWordWrap(True)
        text_col.addWidget(ranges)

        flags = QLabel(
            logistics_ui.LOGISTICS_TARIFFS_META_FLAGS_TEMPLATE.format(
                amount=self.record.get("amountText") or logistics_ui.LOGISTICS_EMPTY_VALUE_TEXT,
                currency=self.record.get("currency", "TRY"),
                amount_mode=self.record.get("amountModeText") or logistics_ui.LOGISTICS_TARIFFS_AMOUNT_MODE_INCLUDED_TEXT,
                status=(
                    logistics_ui.LOGISTICS_TARIFFS_ACTIVE_TEXT
                    if self.record.get("isActive")
                    else logistics_ui.LOGISTICS_TARIFFS_PASSIVE_TEXT
                ),
            ),
            objectName="InvoiceMeta",
        )
        flags.setWordWrap(True)
        text_col.addWidget(flags)

        root.addLayout(text_col, 1)

        self.select_button = QPushButton(FINANCE_CARGO_TARIFF_SELECT_BUTTON_TEXT, self)
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
        self.select_button.setText(
            FINANCE_CARGO_TARIFF_SELECTED_BUTTON_TEXT if picked else FINANCE_CARGO_TARIFF_SELECT_BUTTON_TEXT
        )
        self.select_button.style().unpolish(self.select_button)
        self.select_button.style().polish(self.select_button)
        self.select_button.update()


class LogisticsCargoTariffsWorkspaceAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, window: "LogisticsCargoTariffsWindow") -> None:
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
        return logistics_ui.LOGISTICS_TARIFFS_EDIT_GUIDANCE

    def bulk_guidance_message(self) -> str:
        return logistics_ui.LOGISTICS_TARIFFS_BULK_GUIDANCE


class LogisticsCargoTariffsWindow(QWidget):
    itemsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("LogisticsRoot")
        self.setStyleSheet(FINANCE_STYLE)
        self.setWindowTitle(logistics_ui.LOGISTICS_TARIFFS_WINDOW_TITLE)
        self.setWindowIcon(QIcon(os.path.join(ASSETS_DIR, "logistics-cargo-tariffs-icon.png")))
        self.setGeometry(220, 120, 1500, 860)

        self._has_loaded_once = False
        self._records: list[dict[str, object]] = []
        self._record_map: dict[int, dict[str, object]] = {}
        self._active_pk: int = 0
        self._selected_pks: set[int] = set()
        self._left_mode: str = "edit"
        self._left_stick_size = 760
        self._preferred_left_panel_width: int | None = None
        self._current_page = 1
        self._page_size = 50
        self._reload_queued = False
        self._reload_worker: SyncWorker | None = None
        self._reload_seq = 0
        self._bulk_accept_worker: SyncWorker | None = None
        self._catalog_refresh_pending = False

        self._search_timer = QTimer(self)
        self._search_timer.setInterval(250)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.reload_items)
        self._active_card_timer = QTimer(self)
        self._active_card_timer.setInterval(42)
        self._active_card_timer.timeout.connect(self._tick_active_card_animation)
        self._catalog_refresh_timer = QTimer(self)
        self._catalog_refresh_timer.setInterval(0)
        self._catalog_refresh_timer.setSingleShot(True)
        self._catalog_refresh_timer.timeout.connect(self._refresh_catalog_driven_combos)

        self._workspace = RecordWorkspaceScaffold(
            self,
            empty_placeholder_text="Gösterilecek kargo tarifesi bulunamadı.",
            left_title="Düzenle",
            left_subtitle="Düzenlemek için sağdaki listeden bir kargo tarifesi seç.",
            filters_title="Filtreler",
            filters_subtitle="Yazdıkça otomatik uygular.",
            records_title="Kargo Tarifeleri",
            records_subtitle="Lojistik kargo tarifesi kayıtları",
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": "Yeni kargo tarifesi",
                    "icon_path": str(ASSETS_DIR / "yeni-kayit.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": "Kargo tarifesi düzenle",
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
                "min_left_width": 420,
                "min_right_width": 300,
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
        self._workspace.right_card.setMinimumWidth(0)
        self._workspace.filters_card.setMinimumWidth(0)
        self._workspace.records_card.setMinimumWidth(0)

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
        editor_layout.setContentsMargins(0, 0, 6, 0)
        editor_layout.setHorizontalSpacing(12)
        editor_layout.setVerticalSpacing(12)
        editor_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        editor_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        editor_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.editor_summary_label = QLabel(
            logistics_ui.LOGISTICS_TARIFFS_SELECTED_TEMPLATE.format(count=logistics_ui.LOGISTICS_EMPTY_VALUE_TEXT),
            objectName="StatusInfo",
        )
        editor_layout.addRow(self.editor_summary_label)

        self.tariff_name_input = QLineEdit(self)
        self.tariff_name_input.setObjectName("Input")
        self.tariff_name_input.setPlaceholderText(logistics_ui.LOGISTICS_TARIFFS_NAME_PLACEHOLDER)
        self.tariff_name_input.setMinimumHeight(42)
        editor_layout.addRow(QLabel(logistics_ui.LOGISTICS_TARIFFS_NAME_LABEL, objectName="FieldLabel"), self.tariff_name_input)

        self.tariff_description_input = QPlainTextEdit(self)
        self.tariff_description_input.setObjectName("MethodText")
        self.tariff_description_input.setPlaceholderText(logistics_ui.LOGISTICS_TARIFFS_DESCRIPTION_PLACEHOLDER)
        self.tariff_description_input.setMinimumHeight(150)
        editor_layout.addRow(QLabel(logistics_ui.LOGISTICS_TARIFFS_DESCRIPTION_LABEL, objectName="FieldLabel"), self.tariff_description_input)

        self.platform_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_PLATFORM_LABEL, objectName="FieldLabel")
        self.platform_combo = SwitchSelectWidget(self, multi=False, include_all=False, empty_text="Seçiniz")
        self.platform_combo.setPlaceholderText(logistics_ui.LOGISTICS_TARIFFS_PLATFORM_PLACEHOLDER)
        for label, key in logistics_cargo_tariff_platform_options(include_all=False):
            self.platform_combo.addItem(label, key)
        self.platform_combo.setMinimumHeight(42)
        self.platform_combo.currentIndexChanged.connect(self._on_editor_platform_changed)
        editor_layout.addRow(self.platform_label, self.platform_combo)

        self.provider_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_PROVIDER_LABEL, objectName="FieldLabel")
        self.provider_combo = SwitchSelectWidget(self, multi=False, include_all=False, empty_text="Seçiniz")
        self.provider_combo.setPlaceholderText(logistics_ui.LOGISTICS_TARIFFS_PROVIDER_PLACEHOLDER)
        self.provider_combo.setMinimumHeight(42)
        editor_layout.addRow(self.provider_label, self.provider_combo)

        self.desi_range_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_DESI_RANGE_LABEL, objectName="FieldLabel")
        self.desi_range_input = _NumericRangeInputs(
            self,
            decimals=2,
            left_placeholder="Min desi",
            right_placeholder="Max desi",
        )
        editor_layout.addRow(self.desi_range_label, self.desi_range_input)

        self.sale_price_range_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_PRICE_RANGE_LABEL, objectName="FieldLabel")
        self.sale_price_range_input = _CurrencyRangeInputs(
            self,
            decimals=2,
            currency="TRY",
            left_placeholder="Min satış fiyatı",
            right_placeholder="Max satış fiyatı",
        )
        editor_layout.addRow(self.sale_price_range_label, self.sale_price_range_input)

        self.amount_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_AMOUNT_GROUP_LABEL, objectName="FieldLabel")
        amount_wrap = QWidget(self)
        amount_layout = QVBoxLayout(amount_wrap)
        amount_layout.setContentsMargins(0, 0, 0, 0)
        amount_layout.setSpacing(8)
        amount_row = QHBoxLayout()
        amount_row.setContentsMargins(0, 0, 0, 0)
        amount_row.setSpacing(8)
        self.amount_input = CurrencyAmountInput(
            self,
            decimals=2,
            currency="TRY",
            placeholder=logistics_ui.LOGISTICS_TARIFFS_AMOUNT_PLACEHOLDER,
        )
        self.amount_input.setPlaceholderText(logistics_ui.LOGISTICS_TARIFFS_AMOUNT_PLACEHOLDER)
        self.amount_input.setMinimumHeight(50)
        amount_row.addWidget(self.amount_input, 1)
        self.amount_mode_switch = SwitchButton(self)
        self.amount_mode_switch.setChecked(True)
        self.amount_mode_switch.toggled.connect(self._sync_vat_rate_visibility)
        self.currency_combo = SwitchSelectWidget(self, multi=False, include_all=False, empty_text="Seçiniz")
        self.currency_combo.setPlaceholderText(logistics_ui.LOGISTICS_TARIFFS_CURRENCY_PLACEHOLDER)
        for currency in FINANCE_CURRENCY_OPTIONS:
            self.currency_combo.addItem(currency, currency)
        self.currency_combo.setMinimumHeight(42)
        self.currency_combo.setMinimumWidth(120)
        self.currency_combo.setMaximumWidth(140)
        self.currency_combo.currentIndexChanged.connect(self._sync_amount_currency_badge)
        amount_layout.addLayout(amount_row)
        self.amount_tax_row = QWidget(self)
        amount_tax_row_layout = QHBoxLayout(self.amount_tax_row)
        amount_tax_row_layout.setContentsMargins(0, 0, 0, 0)
        amount_tax_row_layout.setSpacing(10)
        self.amount_mode_net_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_AMOUNT_EXCLUDED_LABEL, objectName="SubTitle")
        self.amount_mode_gross_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_AMOUNT_INCLUDED_LABEL, objectName="SubTitle")
        amount_tax_row_layout.addWidget(self.amount_mode_net_label, 0)
        amount_tax_row_layout.addWidget(self.amount_mode_switch, 0)
        amount_tax_row_layout.addWidget(self.amount_mode_gross_label, 0)
        amount_tax_row_layout.addStretch(1)
        editor_layout.addRow(self.amount_label, amount_wrap)
        self.currency_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_CURRENCY_LABEL, objectName="FieldLabel")
        editor_layout.addRow(self.currency_label, self.currency_combo)
        self.amount_tax_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_VAT_COST_LABEL, objectName="FieldLabel")
        editor_layout.addRow(self.amount_tax_label, self.amount_tax_row)

        self.vat_rate_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_VAT_RATE_LABEL, objectName="FieldLabel")
        self.vat_rate_host = QWidget(self)
        vat_rate_row = QHBoxLayout(self.vat_rate_host)
        vat_rate_row.setContentsMargins(0, 0, 0, 0)
        vat_rate_row.setSpacing(0)
        self.vat_rate_input = CircularPercentageInput(self, decimals=2, diameter=118)
        self.vat_rate_input.setPlaceholderText(logistics_ui.LOGISTICS_TARIFFS_VAT_PLACEHOLDER)
        vat_rate_row.addWidget(self.vat_rate_input, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        vat_rate_row.addStretch(1)
        editor_layout.addRow(self.vat_rate_label, self.vat_rate_host)
        self._cargo_form_rows = {
            "cargoProvider": (self.provider_label, self.provider_combo),
            "desiRange": (self.desi_range_label, self.desi_range_input),
            "salePriceRange": (self.sale_price_range_label, self.sale_price_range_input),
            "amount": (self.amount_label, amount_wrap),
            "vatRate": (self.vat_rate_label, self.vat_rate_host),
        }

        status_wrap = QWidget(self)
        status_row = QHBoxLayout(status_wrap)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(10)
        self.active_switch = SwitchButton(self)
        self.active_switch.setChecked(True)
        self.active_status_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_ACTIVE_TEXT, objectName="StatusInfo")
        self.active_status_label.setMinimumWidth(56)
        self.active_switch.clicked.connect(self._sync_active_status_label)
        status_row.addWidget(self.active_switch, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.active_status_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        status_row.addStretch(1)
        editor_layout.addRow(QLabel(logistics_ui.LOGISTICS_TARIFFS_STATUS_LABEL, objectName="FieldLabel"), status_wrap)

        self._workspace.set_editor_widget(editor_host)

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text="Formu Temizle",
            save_new_text="Kargo Tarifesini Kaydet",
            save_edit_text="Güncelle",
            delete_text="Sil",
        )
        self.btn_new_tariff = self._workspace.editor_action_bar.clear_button
        self.btn_save_tariff = self._workspace.editor_action_bar.save_button
        self.btn_delete_tariff = self._workspace.editor_action_bar.delete_button
        self._workspace.editor_action_bar.clearRequested.connect(self._new_item)
        self._workspace.editor_action_bar.saveRequested.connect(self._save_item)
        self._workspace.editor_action_bar.deleteRequested.connect(self._delete_active_item)

        bulk_content = QWidget(self.bulk_panel)
        bulk_layout = QVBoxLayout(bulk_content)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.setSpacing(8)
        bulk_layout.addWidget(QLabel(logistics_ui.LOGISTICS_TARIFFS_BULK_TITLE, objectName="SectionTitle"))
        self.bulk_summary_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_SELECTED_TEMPLATE.format(count=0), objectName="StatusInfo")
        bulk_layout.addWidget(self.bulk_summary_label)
        bulk_hint = QLabel(logistics_ui.LOGISTICS_TARIFFS_BULK_HINT, objectName="Muted")
        bulk_hint.setWordWrap(True)
        bulk_layout.addWidget(bulk_hint)
        self.btn_accept_selected = QPushButton(logistics_ui.LOGISTICS_TARIFFS_BULK_ACCEPT_TEXT, self)
        self.btn_accept_selected.setObjectName("Secondary")
        self.btn_accept_selected.setMinimumHeight(42)
        self.btn_delete_selected = QPushButton(logistics_ui.LOGISTICS_TARIFFS_BULK_DELETE_TEXT, self)
        self.btn_delete_selected.setObjectName("Danger")
        self.btn_delete_selected.setMinimumHeight(42)
        self.btn_accept_selected.clicked.connect(self._accept_pending_tariffs_bulk)
        self.btn_delete_selected.clicked.connect(self._delete_selected_items)
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
        self.search_input.setPlaceholderText(logistics_ui.LOGISTICS_TARIFFS_SEARCH_PLACEHOLDER)
        self.search_input.textChanged.connect(self._schedule_reload)
        search_row.addWidget(self.search_input, 1)

        self.btn_reset_filters = QPushButton(logistics_ui.LOGISTICS_FILTER_CLEAR_TEXT, self)
        self.btn_reset_filters.setObjectName("SoftDanger")
        self.btn_reset_filters.clicked.connect(self._reset_filters)
        search_row.addWidget(self.btn_reset_filters, 0, alignment=Qt.AlignmentFlag.AlignRight)
        filter_layout.addLayout(search_row)

        filter_row = QHBoxLayout()
        self.filter_platform_combo = SwitchSelectWidget(
            self,
            title=logistics_ui.LOGISTICS_TARIFFS_PLATFORM_LABEL,
            all_text=logistics_ui.LOGISTICS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
        )
        for label, key in logistics_cargo_tariff_platform_options():
            self.filter_platform_combo.addItem(label, key)
        self.filter_platform_combo.setMinimumWidth(0)
        self.filter_platform_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.filter_platform_combo.currentIndexChanged.connect(self._on_filter_platform_changed)
        filter_row.addWidget(self.filter_platform_combo, 1)

        self.filter_provider_combo = SwitchSelectWidget(
            self,
            title=logistics_ui.LOGISTICS_CARGO_PROVIDERS_BUTTON_TEXT,
            all_text=logistics_ui.LOGISTICS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
        )
        self.filter_provider_combo.setMinimumWidth(0)
        self.filter_provider_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.filter_provider_combo.currentIndexChanged.connect(self.reload_items)
        filter_row.addWidget(self.filter_provider_combo, 1)

        self.filter_active_combo = SwitchSelectWidget(
            self,
            title=logistics_ui.LOGISTICS_TARIFFS_STATUS_LABEL,
            all_text=logistics_ui.LOGISTICS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
        )
        self.filter_active_combo.addItem(logistics_ui.LOGISTICS_FILTER_ALL_TEXT, "")
        self.filter_active_combo.addItem(logistics_ui.LOGISTICS_TARIFFS_ACTIVE_FILTER_TEXT, logistics_ui.LOGISTICS_TARIFFS_ACTIVE_FILTER_TEXT)
        self.filter_active_combo.addItem(logistics_ui.LOGISTICS_TARIFFS_PASSIVE_FILTER_TEXT, logistics_ui.LOGISTICS_TARIFFS_PASSIVE_FILTER_TEXT)
        self.filter_active_combo.setMinimumWidth(0)
        self.filter_active_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.filter_active_combo.currentIndexChanged.connect(self.reload_items)
        filter_row.addWidget(self.filter_active_combo, 1)
        self.filter_source_combo = SwitchSelectWidget(
            self,
            title="Kaynak",
            all_text=logistics_ui.LOGISTICS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
        )
        self.filter_source_combo.addItem(logistics_ui.LOGISTICS_FILTER_ALL_TEXT, "")
        self.filter_source_combo.addItem(logistics_ui.LOGISTICS_FILTER_PENDING_TEXT, logistics_ui.LOGISTICS_FILTER_PENDING_VALUE)
        self.filter_source_combo.addItem(logistics_ui.LOGISTICS_FILTER_SAVED_TEXT, logistics_ui.LOGISTICS_FILTER_SAVED_VALUE)
        self.filter_source_combo.setMinimumWidth(0)
        self.filter_source_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.filter_source_combo.currentIndexChanged.connect(self.reload_items)
        filter_row.addWidget(self.filter_source_combo, 1)
        filter_layout.addLayout(filter_row)

        self.filter_summary_label = QLabel(logistics_ui.LOGISTICS_TARIFFS_TOTAL_TEMPLATE.format(count=0), objectName="StatusInfo")
        filter_layout.addWidget(self.filter_summary_label)
        self._workspace.set_filters_widget(filters_host)

        self.list_widget = LogisticsCargoTariffsListWidget(
            self._workspace.records_card.body_host,
            empty_placeholder_text="Gösterilecek kargo tarifesi bulunamadı.",
        )
        self.list_widget.selection_changed.connect(self._on_card_selection_changed)
        self.list_widget.page_changed.connect(lambda *_args: self._update_pagination_ui())
        self._workspace.set_list_widget(self.list_widget)
        self.btn_bulk_select_toggle = self._workspace.footer_bar.select_toggle
        self._workspace.set_records_summary_text("0 / 0 kayıt")
        self._workspace.set_filters_footer_text(logistics_ui.LOGISTICS_TARIFFS_TOTAL_TEMPLATE.format(count=0))
        self._workspace_shell.close_left_panel()

        self._workspace_adapter = LogisticsCargoTariffsWorkspaceAdapter(self)
        self._workspace_controller = self._workspace.create_behavior_controller(adapter=self._workspace_adapter)
        self._set_left_mode("edit")
        self._load_editor_payload(None)
        self._refresh_editor_platform_combo()
        self._refresh_filter_platform_combo()
        self._refresh_filter_provider_combo()
        marketplace_signals.marketplaces_changed.connect(self._request_catalog_combo_refresh)
        logistics_signals.cargo_providers_changed.connect(self._request_catalog_combo_refresh)

    def _request_catalog_combo_refresh(self) -> None:
        if not self.isVisible():
            self._catalog_refresh_pending = True
            return
        self._catalog_refresh_timer.start()

    def _refresh_editor_platform_combo(self, preferred_code: str = "") -> None:
        current_code = str(preferred_code or self.platform_combo.currentData() or "").strip()
        with QSignalBlocker(self.platform_combo):
            self.platform_combo.clear()
            for label, key in logistics_cargo_tariff_platform_options(include_all=False):
                self.platform_combo.addItem(label, key)
            self._set_combo_value(self.platform_combo, current_code)

    def _refresh_filter_platform_combo(self, preferred_code: str = "") -> None:
        current_code = str(preferred_code or self.filter_platform_combo.currentData() or "").strip()
        with QSignalBlocker(self.filter_platform_combo):
            self.filter_platform_combo.clear()
            for label, key in logistics_cargo_tariff_platform_options():
                self.filter_platform_combo.addItem(label, key)
            self._set_combo_value(self.filter_platform_combo, current_code)

    def _refresh_catalog_driven_combos(self) -> None:
        editor_platform = str(self.platform_combo.currentData() or "").strip()
        editor_provider = str(self.provider_combo.currentData() or "").strip()
        filter_platform = str(self.filter_platform_combo.currentData() or "").strip()
        filter_provider = str(self.filter_provider_combo.currentData() or "").strip()

        self._refresh_editor_platform_combo(editor_platform)
        self._refresh_filter_platform_combo(filter_platform)
        self._refresh_provider_combo(editor_provider)
        self._refresh_filter_provider_combo(filter_provider)

        if self._has_loaded_once:
            self.request_reload_items(active_pk=self._active_pk or None, preserve_page=True)

    def showEvent(self, event):
        super().showEvent(event)
        if self._catalog_refresh_pending:
            self._catalog_refresh_pending = False
            self._catalog_refresh_timer.start()
        if not self._has_loaded_once:
            self._has_loaded_once = True
            self._apply_initial_splitter_ratio()
            self._close_left_panel()  # Ensures the panel is closed on startup
            self._workspace.set_list_loading(True, "Kargo tarifeleri yükleniyor...")
            QTimer.singleShot(0, self.request_reload_items)

    def _apply_initial_splitter_ratio(self) -> None:
        if self._preferred_left_panel_width is not None:
            return
        total = self._splitter_total_size()
        if total <= 0:
            return
        left = max(420, int(total // 2))
        right = max(300, int(total - left))
        if left + right > total:
            left = max(420, total - 300)
            right = max(300, total - left)
        self._preferred_left_panel_width = left
        self._splitter.setSizes([left, right])

    def request_reload_items(self, *, active_pk: int | None = None, preserve_page: bool = False) -> None:
        if self._reload_queued:
            return
        self._reload_queued = True
        self._workspace.set_list_loading(True, "Kargo tarifeleri yükleniyor...")

        def _run() -> None:
            self._reload_queued = False
            self.reload_items(active_pk=active_pk, preserve_page=preserve_page)

        QTimer.singleShot(0, _run)

    def _schedule_reload(self) -> None:
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
    def _is_pending_builtin_tariff(record: dict[str, object] | None) -> bool:
        payload = dict(record or {})
        return bool(payload.get("isBuiltin")) and not bool(payload.get("isBuiltinAccepted"))

    @staticmethod
    def _is_seed_removed_builtin_tariff(record: dict[str, object] | None) -> bool:
        payload = dict(record or {})
        return bool(payload.get("isSeedRemoved"))

    def _is_builtin_cargo_tariff(self, record: dict[str, object] | None = None) -> bool:
        payload = dict(record or (self._record_map.get(self._active_pk) or {}))
        return bool(payload.get("isBuiltin")) and not bool(payload.get("isSeedRemoved"))

    def _selected_has_builtin_cargo_tariffs(self) -> bool:
        return any(
            bool((self._record_map.get(pk) or {}).get("isBuiltin"))
            and not bool((self._record_map.get(pk) or {}).get("isSeedRemoved"))
            for pk in self._selected_pks
        )

    def _build_card_record(self, record: dict[str, object]) -> OrdersStyleCardRecord:
        subtitle = (
            f"Platform: {record.get('platform') or '-'} | "
            f"Kargo: {record.get('providerText') or '-'}"
        )
        extra_parts = [
            f"Desi: {record.get('desiRangeText') or '-'}",
            f"Fiyat: {record.get('salePriceRangeText') or '-'}",
            f"Ücret: {record.get('amountText') or '-'} {record.get('currency', 'TRY')}",
            str(record.get("amountModeText") or "KDV dahil"),
        ]
        if self._is_pending_builtin_tariff(record):
            extra_parts.append(FINANCE_CARGO_TARIFF_PENDING_BADGE_TEXT)
        if self._is_seed_removed_builtin_tariff(record):
            extra_parts.append("Seed'den kalkti | Silme onerisi")
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
            logo_path=os.path.join(ASSETS_DIR, "logistics-cargo-tariffs-icon.png"),
            payload=record,
            _selected=int(record.get("pk") or 0) in self._selected_pks,
        )

    def _refresh_left_panel_header(self) -> None:
        title = "Düzenle"
        subtitle = "Düzenlemek için sağdaki listeden bir kargo tarifesi seç."
        if self._left_mode == "new":
            title = "Yeni Ekle"
            subtitle = "Yeni kargo tarifesini doldurup kaydet."
        elif self._left_mode == "bulk":
            title = "Toplu Seçim"
            subtitle = "SEÇ ile işaretlediğin kargo tarifeleri için toplu işlem yap."
        elif self._active_pk > 0 and self._active_pk in self._record_map:
            subtitle = f"Seçili tarife: {str(self._record_map[self._active_pk].get('name') or '-')}"
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
            show_editor and mode_key == "edit" and self._active_pk > 0 and not self._is_builtin_cargo_tariff()
        )
        self._refresh_left_panel_header()
        self._workspace.schedule_editor_layout_refresh()

    def _splitter_total_size(self) -> int:
        return self._workspace_shell.splitter_total_size()

    def _is_left_panel_open(self) -> bool:
        return self._workspace_shell.is_left_panel_open()

    def _open_left_panel(self) -> None:
        preferred_width = self._preferred_left_panel_width
        if preferred_width is None or int(preferred_width) <= 0:
            preferred_width = max(420, int(self._splitter_total_size() // 2))
        self._workspace_shell.open_left_panel(
            left_width=max(420, int(preferred_width)),
            min_left=420,
            min_right=300,
        )

    def _close_left_panel(self) -> None:
        self._workspace_shell.close_left_panel()

    def _sync_sidebar_state_from_splitter(self) -> None:
        try:
            if self._workspace_shell.is_left_panel_open():
                sizes = list(self._splitter.sizes() or [])
                if sizes:
                    self._preferred_left_panel_width = max(420, int(sizes[0] or 0))
        except Exception:
            pass
        controller = getattr(self, "_workspace_controller", None)
        if controller is not None:
            controller.sync_state()

    def _current_left_guidance_message(self) -> str:
        panel_open = self._is_left_panel_open()
        if panel_open and self._left_mode == "edit" and self._active_pk <= 0:
            return "Düzenlemek için sağdaki listeden bir kargo tarifesi seç."
        if panel_open and self._left_mode == "bulk" and not bool(self._selected_pks):
            return "Toplu işlem için sağdaki listeden en az bir tarifeyi SEÇ ile işaretle."
        return ""

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

    def _refresh_provider_combo(self, preferred_code: str = "") -> None:
        current_platform = str(self.platform_combo.currentData() or "").strip()
        with QSignalBlocker(self.provider_combo):
            self.provider_combo.clear()
            self.provider_combo.addItem(logistics_ui.LOGISTICS_TARIFFS_SELECT_TEXT, "")
            for label, key in logistics_cargo_provider_options(current_platform, include_all=False):
                self.provider_combo.addItem(label, key)
            self._set_combo_value(self.provider_combo, preferred_code)

    def _refresh_filter_provider_combo(self, preferred_code: str = "") -> None:
        current_platform = str(self.filter_platform_combo.currentData() or "").strip()
        with QSignalBlocker(self.filter_provider_combo):
            self.filter_provider_combo.clear()
            for label, key in logistics_cargo_provider_options(current_platform, include_all=True):
                self.filter_provider_combo.addItem(label, key)
            self._set_combo_value(self.filter_provider_combo, preferred_code)

    def _on_editor_platform_changed(self, *_args) -> None:
        current_provider = str(self.provider_combo.currentData() or "").strip()
        self._refresh_provider_combo(current_provider)
        self._apply_cargo_platform_form_rules(self.platform_combo.currentData())

    def _on_filter_platform_changed(self, *_args) -> None:
        current_provider = str(self.filter_provider_combo.currentData() or "").strip()
        self._refresh_filter_provider_combo(current_provider)
        self.reload_items()

    def _set_combo_value(self, combo, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _sync_amount_currency_badge(self, *_args) -> None:
        currency = str(self.currency_combo.currentData() or "TRY")
        self.amount_input.setCurrency(currency)
        self.sale_price_range_input.setCurrency(currency)

    def _set_numeric_value(self, widget: QWidget, value: object) -> None:
        if hasattr(widget, "setValue"):
            try:
                widget.setValue(None if value in (None, "") else float(value))
                return
            except Exception:
                pass
        if hasattr(widget, "setText"):
            widget.setText("" if value in (None, "") else compact_number_text(value))

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

    def _set_cargo_form_row_visible(self, row_key: str, visible: bool) -> None:
        label_widget, field_widget = self._cargo_form_rows.get(row_key, (None, None))
        if label_widget is not None:
            label_widget.setVisible(bool(visible))
            label_widget.setEnabled(bool(visible))
        if field_widget is not None:
            field_widget.setVisible(bool(visible))
            field_widget.setEnabled(bool(visible))

    def _apply_cargo_platform_form_rules(self, platform_code: object | None) -> None:
        visible_fields = set(logistics_cargo_tariff_visible_fields(platform_code))
        for row_key in self._cargo_form_rows:
            self._set_cargo_form_row_visible(row_key, row_key in visible_fields)
        self._set_cargo_form_row_visible("vatRate", True)
        self._sync_vat_rate_visibility()

    def _set_active_card_animation_enabled(self, enabled: bool) -> None:
        self.list_widget.set_active_spin_allowed(bool(enabled))
        self._active_card_timer.stop()

    def _tick_active_card_animation(self) -> None:
        self.list_widget.sync_dynamic_row_width()

    def _load_editor_payload(self, record: dict | None) -> None:
        rec = dict(record or {})
        self.tariff_name_input.setText(str(rec.get("name") or ""))
        self.tariff_description_input.setPlainText(str(rec.get("description") or ""))
        self._set_combo_value(
            self.platform_combo,
            str(rec.get("platformSourceId") or rec.get("platform_source_id") or rec.get("platformCode") or rec.get("platform") or "1"),
        )
        self._refresh_provider_combo(str(rec.get("cargoProviderSourceId") or rec.get("cargo_provider_source_id") or rec.get("cargoProviderCode") or ""))
        self.desi_range_input.setValues(
            None if rec.get("minDesi") in (None, "") else float(rec.get("minDesi")),
            None if rec.get("maxDesi") in (None, "") else float(rec.get("maxDesi")),
        )
        self.sale_price_range_input.setValues(
            None if rec.get("minSalePrice") in (None, "") else float(rec.get("minSalePrice")),
            None if rec.get("maxSalePrice") in (None, "") else float(rec.get("maxSalePrice")),
        )
        self._set_numeric_value(self.amount_input, rec.get("amount"))
        self.amount_mode_switch.setChecked(bool(rec.get("isVatIncluded", True)))
        self._set_combo_value(self.currency_combo, str(rec.get("currency") or "TRY"))
        self._sync_amount_currency_badge()
        self._set_numeric_value(self.vat_rate_input, rec.get("vatRate"))
        self.active_switch.setChecked(bool(rec.get("isActive", True)))
        self._sync_active_status_label()
        self._apply_cargo_platform_form_rules(self.platform_combo.currentData())
        self._sync_vat_rate_visibility()
        self.editor_summary_label.setText(f"Seçili tarife: {str(rec.get('name') or '-')}")
        self._workspace.set_editor_action_delete_available(
            self._active_pk > 0 and self._left_mode == "edit" and not self._is_builtin_cargo_tariff(rec)
        )
        self._refresh_left_panel_header()

    def _collect_payload(self) -> dict[str, object]:
        active = self._record_map.get(self._active_pk, {})
        visible_fields = set(logistics_cargo_tariff_visible_fields(self.platform_combo.currentData()))
        return {
            "pk": active.get("pk"),
            "tariffKey": active.get("tariffKey"),
            "name": self.tariff_name_input.text().strip(),
            "description": self.tariff_description_input.toPlainText().strip(),
            "platformSourceId": str(self.platform_combo.currentData() or "1"),
            "cargoProviderSourceId": str(self.provider_combo.currentData() or "").strip() if "cargoProvider" in visible_fields else "",
            "cargoProviderName": (
                "" if "cargoProvider" not in visible_fields or not str(self.provider_combo.currentData() or "").strip()
                else str(self.provider_combo.currentText() or "").strip()
            ),
            "minDesi": self.desi_range_input.leftText().strip() if "desiRange" in visible_fields else "",
            "maxDesi": self.desi_range_input.rightText().strip() if "desiRange" in visible_fields else "",
            "minSalePrice": self.sale_price_range_input.leftText().strip() if "salePriceRange" in visible_fields else "",
            "maxSalePrice": self.sale_price_range_input.rightText().strip() if "salePriceRange" in visible_fields else "",
            "amount": self.amount_input.text().strip(),
            "currency": str(self.currency_combo.currentData() or "TRY"),
            "isVatIncluded": self.amount_mode_switch.isChecked(),
            "vatRate": self.vat_rate_input.text().strip() if "vatRate" in visible_fields else "",
            "isActive": self.active_switch.isChecked(),
        }

    def _new_item(self, *, open_panel: bool = True) -> None:
        self._active_pk = 0
        self._set_left_mode("new")
        self._load_editor_payload(
            {
                "name": "",
                "description": "",
                "platformSourceId": 1,
                "cargoProviderSourceId": "",
                "minDesi": "",
                "maxDesi": "",
                "minSalePrice": "",
                "maxSalePrice": "",
                "amount": "",
                "currency": "TRY",
                "isVatIncluded": True,
                "vatRate": "",
                "isActive": True,
            }
        )
        self._sync_card_states()
        if open_panel:
            self._open_left_panel()

    def _save_item(self) -> None:
        result = save_logistics_cargo_tariff(self._collect_payload())
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
        if self._is_builtin_cargo_tariff():
            MessageHandler.show(self, Result.fail("Önerilen kargo tarifeleri doğrudan silinemez.", close_dialog=False), only_errors=True)
            return
        result = delete_logistics_cargo_tariff(self._active_pk)
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
        if self._selected_has_builtin_cargo_tariffs():
            MessageHandler.show(self, Result.fail("Önerilen kargo tarifeleri toplu silinemez.", close_dialog=False), only_errors=True)
            return
        result = delete_logistics_cargo_tariffs(sorted(self._selected_pks))
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        self._selected_pks.clear()
        self._active_pk = 0
        self.reload_items()
        self.itemsChanged.emit()
    def _reset_filters(self) -> None:
        self.search_input.clear()
        self.filter_platform_combo.setCurrentIndex(0)
        self._refresh_filter_provider_combo()
        self.filter_provider_combo.setCurrentIndex(0)
        self.filter_active_combo.setCurrentIndex(0)
        self.filter_source_combo.setCurrentIndex(0)
        self.reload_items()

    def _switch_source_filter_to_saved_if_pending(self) -> None:
        if str(self.filter_source_combo.currentData() or "").strip().lower() != "pending":
            return
        saved_index = self.filter_source_combo.findData("saved")
        if saved_index >= 0:
            self.filter_source_combo.setCurrentIndex(saved_index)

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
        if self._is_pending_builtin_tariff(record_payload):
            if selected:
                self._accept_builtin_tariff(key)
            return
        if self._is_seed_removed_builtin_tariff(record_payload):
            if selected:
                self._delete_seed_removed_builtin_tariff(key)
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

    def _sync_active_status_label(self, *_args) -> None:
        self.active_status_label.setText("Aktif" if self.active_switch.isChecked() else "Pasif")

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
        self._active_pk = clicked_pk
        record = self._record_map.get(self._active_pk)
        self._set_left_mode("edit")
        self._load_editor_payload(record)
        self._sync_card_states()
        self._open_left_panel()

    def _sync_bulk_summary(self) -> None:
        self.bulk_summary_label.setText(f"Seçili tarife: {len(self._selected_pks)}")
        enabled = bool(self._selected_pks)
        pending_visible = [
            int(row.get("pk") or 0)
            for row in self._records
            if int(row.get("pk") or 0) > 0 and self._is_pending_builtin_tariff(row)
        ]
        pending_selected = [pk for pk in self._selected_pks if pk in pending_visible]
        self.btn_accept_selected.setEnabled(
            bool(pending_selected or pending_visible)
            and not bool(self._bulk_accept_worker is not None and self._bulk_accept_worker.isRunning())
        )
        self.btn_delete_selected.setEnabled(enabled and not self._selected_has_builtin_cargo_tariffs())
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
        if self._is_pending_builtin_tariff(record_payload):
            self._accept_builtin_tariff(key)
            return
        if self._is_seed_removed_builtin_tariff(record_payload):
            self._delete_seed_removed_builtin_tariff(key)
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

    def _accept_builtin_tariff(self, item_pk: int) -> None:
        target = dict(self._record_map.get(int(item_pk or 0)) or {})
        if not self._is_pending_builtin_tariff(target):
            return
        if not AppMessageCenter.confirm(
            self,
            FINANCE_CARGO_TARIFF_ACCEPT_TITLE,
            FINANCE_CARGO_TARIFF_ACCEPT_CONFIRMATION_TEXT,
            default_yes=False,
        ):
            return
        result = accept_logistics_cargo_tariff(int(item_pk or 0))
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        self._search_timer.stop()
        self._switch_source_filter_to_saved_if_pending()
        self.reload_items(active_pk=int(item_pk or 0), preserve_page=True)
        MessageHandler.show(self, result, only_errors=False)
        self.itemsChanged.emit()

    def _delete_seed_removed_builtin_tariff(self, item_pk: int) -> None:
        target = dict(self._record_map.get(int(item_pk or 0)) or {})
        if not self._is_seed_removed_builtin_tariff(target):
            return
        if not AppMessageCenter.confirm(
            self,
            "Kaydi Sil",
            "Bu yerleşik kayıt artık seed katalogda yok. Veritabanından silmek istiyor musun?",
            default_yes=False,
        ):
            return
        result = delete_logistics_cargo_tariff(int(item_pk or 0))
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        self._selected_pks.discard(int(item_pk or 0))
        self.reload_items(preserve_page=True)
        MessageHandler.show(self, result, only_errors=False)
        self.itemsChanged.emit()

    def _start_bulk_accept_worker(self, target_pks: list[int]) -> None:
        if self._bulk_accept_worker is not None and self._bulk_accept_worker.isRunning():
            return
        self._search_timer.stop()
        self.btn_accept_selected.setEnabled(False)
        self._workspace.set_list_loading(True, "Önerilen kargo tarifeleri kullanıma alınıyor...")
        worker = SyncWorker(
            accept_logistics_cargo_tariffs,
            [int(item_pk or 0) for item_pk in target_pks],
            parent=self,
        )
        self._bulk_accept_worker = worker

        def _on_result(result: Result) -> None:
            if not result.success:
                self._workspace.set_list_loading(False)
                MessageHandler.show(self, result, only_errors=True)
                return
            self._switch_source_filter_to_saved_if_pending()
            self.reload_items(preserve_page=True)
            MessageHandler.show(self, result, only_errors=False)
            self.itemsChanged.emit()

        def _on_finished() -> None:
            if self._bulk_accept_worker is worker:
                self._bulk_accept_worker = None
            if not self._reload_queued:
                self._workspace.set_list_loading(False)
            self._sync_bulk_summary()
            worker.deleteLater()

        worker.result_ready.connect(_on_result)
        worker.finished.connect(_on_finished)
        worker.start()

    def _accept_pending_tariffs_bulk(self) -> None:
        target_pks = [
            pk for pk in self._selected_pks
            if self._is_pending_builtin_tariff(self._record_map.get(int(pk or 0)))
        ]
        if not target_pks:
            target_pks = [
                int(row.get("pk") or 0)
                for row in self._records
                if int(row.get("pk") or 0) > 0 and self._is_pending_builtin_tariff(row)
            ]
        if not target_pks:
            return
        if not AppMessageCenter.confirm(
            self,
            "Toplu Kabul",
            f"{len(target_pks)} önerilen kargo tarifesini kullanıma almak istiyor musun?",
            default_yes=False,
        ):
            return
        self._start_bulk_accept_worker(target_pks)

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

    def reload_items(self, *_args, active_pk: int | None = None, preserve_page: bool = False) -> None:
        self._workspace.set_list_loading(True, "Kargo tarifeleri yükleniyor...")
        try:
            self._refresh_filter_provider_combo(str(self.filter_provider_combo.currentData() or "").strip())
        except Exception as exc:
            self._workspace.set_list_loading(False)
            MessageHandler.show(self, Result.fail(map_error_to_message(exc), error=exc), only_errors=True)
            return

        self._reload_seq += 1
        seq = int(self._reload_seq)
        worker = SyncWorker(
            load_logistics_cargo_tariffs,
            search_text=self.search_input.text().strip(),
            platform=str(self.filter_platform_combo.currentData() or "").strip(),
            cargo_provider_code=str(self.filter_provider_combo.currentData() or "").strip(),
            active_state=str(self.filter_active_combo.currentData() or "").strip(),
            source_state=str(self.filter_source_combo.currentData() or "").strip(),
            parent=self,
        )
        self._reload_worker = worker

        def _handle_result(result: Result) -> None:
            if seq != self._reload_seq:
                return
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                return

            data = result.data or {}
            self._records = list(data.get("records") or [])
            if not preserve_page:
                self._current_page = 1
            self._record_map = {int(row.get("pk") or 0): row for row in self._records if int(row.get("pk") or 0) > 0}
            self.filter_summary_label.setText(str(data.get("summary_text") or "Toplam tarife: 0"))
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

        def _handle_finished() -> None:
            if self._reload_worker is worker:
                self._reload_worker = None
            if seq == self._reload_seq:
                self._workspace.set_list_loading(False)
            worker.deleteLater()

        worker.result_ready.connect(_handle_result)
        worker.finished.connect(_handle_finished)
        worker.start()


FinanceCargoTariffsListDelegate = LogisticsCargoTariffsListDelegate
FinanceCargoTariffCard = LogisticsCargoTariffCard
FinanceCargoTariffsWindow = LogisticsCargoTariffsWindow

__all__ = [
    "LogisticsCargoTariffsListDelegate",
    "LogisticsCargoTariffCard",
    "LogisticsCargoTariffsWindow",
    "FinanceCargoTariffsListDelegate",
    "FinanceCargoTariffCard",
    "FinanceCargoTariffsWindow",
    "FINANCE_CARGO_TARIFF_ACCEPT_BUTTON_TEXT",
]

