# Stock/views/views.py
from __future__ import annotations

from typing import Any, Optional
from datetime import datetime
from collections import OrderedDict

from PyQt6.QtCore import Qt, QDateTime, QDate, QTime, QAbstractListModel, QModelIndex, QSize, QEvent, QRect, pyqtSignal, QTimer, QSignalBlocker
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QPixmap, QDoubleValidator, QIcon
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QDialog, QLineEdit,
    QDoubleSpinBox, QFrame,
    QScrollArea, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QCheckBox, QAbstractSpinBox, QInputDialog,
    QListView, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QComboBox,
    QSizePolicy,
)
from Core.views import (
    NumberStepper, SwitchButton, SwitchSelectWidget, NumericPulseLineEdit, CircularPercentageInput, PhoneNumberInput,
    CurrencyAmountInput,
    BadgeButton, LabeledActionInput, AppMessageCenter, QuickAccessSection,
    compose_record_workspace_style,
    RecordWorkspaceBehaviorAdapter, RecordWorkspaceScaffold, RecordWorkspaceListDelegate,
    FileBadgePicker, ExcelTableWidget, DateSelector, TimeSelector, optimized_table_updates
)
from Core.views.tab_widgets import DashboardHeroCard
from Core.threads.sync_worker import SyncWorker
from settings import ASSETS_DIR
from Stock.signals.signals import stock_signals

from Stock.constants.constants import (
    StockItemType,
    StockTxReason,
    StockReferenceType,
    UNIT_OPTIONS,
    ITEM_TYPE_OPTIONS,
    CURRENCY_OPTIONS,
    COUNTRY_OPTIONS,
    CITY_OPTIONS_BY_COUNTRY,
    COUNTRY_PHONE_CODE_BY_COUNTRY,
    PHONE_DIAL_CODE_OPTIONS,
)
from Stock.constants.ui_constants import (
    MODERN_LIGHT_QSS,
    STOCK_NATIVE_LINE_EDIT_QSS,
    STOCK_SEARCH_LINE_EDIT_QSS,
    STOCK_TEXT_EDIT_QSS,
    STOCK_COMBO_QSS,
    STOCK_DOUBLE_SPIN_QSS,
    STOCK_SWITCH_SELECT_QSS,
    STOCK_FILE_BADGE_PICKER_QSS,
    STOCK_NUMBER_STEPPER_QSS,
    STOCK_CARD_INLINE_STOCK_W,
    STOCK_CARD_INLINE_AVG_W,
    STOCK_CARD_INLINE_STOCK_H,
    STOCK_CARD_INLINE_GAP,
    STOCK_IMAGE_PREVIEW_TITLE,
    STOCK_IMAGE_PREVIEW_LOAD_ERROR_TEXT,
    STOCK_IMAGE_PREVIEW_EMPTY_TEXT,
    STOCK_ITEM_SOURCE_BUTTON_TEXT,
    STOCK_TX_SOURCE_BUTTON_TEXT,
    STOCK_TX_ORDER_BUTTON_TEXT,
    STOCK_TX_LISTING_BUTTON_TEXT,
    STOCK_MANAGER_REFRESH_TEXT,
    STOCK_MANAGER_FILTERS_TITLE,
    STOCK_MANAGER_LEFT_EDIT_TITLE,
    STOCK_MANAGER_LEFT_NEW_TITLE,
    STOCK_MANAGER_LEFT_BULK_TITLE,
    STOCK_MANAGER_BULK_TITLE,
    STOCK_MANAGER_CLEAR_TEXT,
    STOCK_MANAGER_SAVE_EDIT_TEXT,
    STOCK_MANAGER_DELETE_TEXT,
    STOCK_MANAGER_RESET_FILTERS_TEXT,
    STOCK_MANAGER_BULK_CLEAR_TEXT,
    STOCK_MANAGER_BULK_DELETE_TEXT,
    STOCK_MANAGER_SIDEBAR_BULK_TOOLTIP,
    STOCK_MANAGER_WORKSPACE_SHELL_KWARGS,
    STOCK_MANAGER_EMPTY_TEXT,
    STOCK_ITEMS_EMPTY_TEXT,
    STOCK_TX_EMPTY_TEXT,
    STOCK_MANAGER_CARD_ROW_HEIGHT,
    STOCK_CARD_FONT_FAMILY,
    STOCK_CARD_PLACEHOLDER_TEXT_COLOR,
    STOCK_CARD_ICON_PLACEHOLDER_COLOR,
    STOCK_CARD_TITLE_COLOR,
    STOCK_CARD_BODY_COLOR,
    STOCK_CARD_MUTED_COLOR,
    STOCK_CARD_ACTION_TEXT_COLOR,
    STOCK_CARD_AVATAR_FILL_COLOR,
    STOCK_CARD_AVATAR_TEXT_COLOR,
    STOCK_CARD_BADGE_BORDER_COLOR,
    STOCK_CARD_BADGE_FILL_COLOR,
    STOCK_CARD_BADGE_TEXT_COLOR,
    STOCK_CARD_SELECTED_BUTTON_FILL_COLOR,
    STOCK_CARD_SELECTED_BUTTON_BORDER_COLOR,
    STOCK_CARD_HOVER_BUTTON_FILL_COLOR,
    STOCK_CARD_HOVER_BUTTON_BORDER_COLOR,
    STOCK_CARD_IDLE_BUTTON_FILL_COLOR,
    STOCK_CARD_IDLE_BUTTON_BORDER_COLOR,
    STOCK_CARD_PLACEHOLDER_FONT_SIZE,
    STOCK_CARD_TITLE_FONT_SIZE,
    STOCK_CARD_META_FONT_SIZE,
    STOCK_CARD_ACTION_FONT_SIZE,
    STOCK_CARD_AVATAR_FONT_SIZE,
)
def _stock_action(name: str):
    from Stock.views import actions

    return getattr(actions, name)


def _lazy_stock_action(name: str):
    def _call(*args, **kwargs):
        return _stock_action(name)(*args, **kwargs)

    _call.__name__ = name
    return _call


action_create_item = _lazy_stock_action("action_create_item")
action_generate_unique_barcode = _lazy_stock_action("action_generate_unique_barcode")
action_update_item = _lazy_stock_action("action_update_item")
action_delete_item = _lazy_stock_action("action_delete_item")
action_create_brand = _lazy_stock_action("action_create_brand")
action_update_brand = _lazy_stock_action("action_update_brand")
action_delete_brand = _lazy_stock_action("action_delete_brand")
action_list_brands = _lazy_stock_action("action_list_brands")
action_create_company = _lazy_stock_action("action_create_company")
action_update_company = _lazy_stock_action("action_update_company")
action_delete_company = _lazy_stock_action("action_delete_company")
action_list_companies = _lazy_stock_action("action_list_companies")
action_create_sub_group = _lazy_stock_action("action_create_sub_group")
action_update_sub_group = _lazy_stock_action("action_update_sub_group")
action_delete_sub_group = _lazy_stock_action("action_delete_sub_group")
action_list_sub_groups = _lazy_stock_action("action_list_sub_groups")
action_list_upper_groups = _lazy_stock_action("action_list_upper_groups")
action_list_upper_group_records = _lazy_stock_action("action_list_upper_group_records")
action_create_upper_group = _lazy_stock_action("action_create_upper_group")
action_update_upper_group = _lazy_stock_action("action_update_upper_group")
action_delete_upper_group = _lazy_stock_action("action_delete_upper_group")
action_create_warehouse = _lazy_stock_action("action_create_warehouse")
action_update_warehouse = _lazy_stock_action("action_update_warehouse")
action_delete_warehouse = _lazy_stock_action("action_delete_warehouse")
action_list_items = _lazy_stock_action("action_list_items")
action_list_warehouses = _lazy_stock_action("action_list_warehouses")
action_get_on_hand = _lazy_stock_action("action_get_on_hand")
action_manual_in = _lazy_stock_action("action_manual_in")
action_manual_out = _lazy_stock_action("action_manual_out")
action_update_tx_edit_fields = _lazy_stock_action("action_update_tx_edit_fields")
action_list_txs_by_ids = _lazy_stock_action("action_list_txs_by_ids")
action_list_txs_filtered = _lazy_stock_action("action_list_txs_filtered")
action_export_txs_excel = _lazy_stock_action("action_export_txs_excel")
action_list_item_balances = _lazy_stock_action("action_list_item_balances")
action_adjust_item_stock_to = _lazy_stock_action("action_adjust_item_stock_to")

def _country_default_dial_code(country: Any) -> str:
    country_name = str(country or "").strip()
    if not country_name:
        return "+90"
    return str(COUNTRY_PHONE_CODE_BY_COUNTRY.get(country_name) or "+90")


def _sync_phone_country_code(phone_widget: PhoneNumberInput, country: Any) -> None:
    if phone_widget is None or not phone_widget.is_empty():
        return
    phone_widget.setCurrentDialCode(_country_default_dial_code(country))


def _btn(text: str, kind: str = "Ghost", min_h: int = 44) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(kind)
    b.setMinimumHeight(min_h)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setAutoDefault(False)
    b.setDefault(False)
    return b


def _inline_action_btn(
    text: str,
    kind: str = "InlineAction",
    min_h: int = 38,
    *,
    min_w: int | None = None,
) -> QPushButton:
    b = _btn(text, kind, min_h)
    target_w = int(min_w or max(88, b.sizeHint().width() + 18))
    b.setMinimumWidth(target_w)
    b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return b


def _has_stock_composite_ancestor(widget: QWidget | None) -> bool:
    composite_types = (
        SwitchSelectWidget,
        FileBadgePicker,
        CurrencyAmountInput,
        NumberStepper,
        PhoneNumberInput,
        DateSelector,
        TimeSelector,
    )
    parent = widget.parentWidget() if widget is not None else None
    while parent is not None:
        if isinstance(parent, composite_types):
            return True
        parent = parent.parentWidget()
    return False


def _apply_stock_native_field_theme(root: QWidget | None) -> None:
    if root is None:
        return

    for widget in root.findChildren(QLineEdit):
        if _has_stock_composite_ancestor(widget):
            continue
        if widget.objectName() == "Search":
            widget.setStyleSheet(STOCK_SEARCH_LINE_EDIT_QSS)
        elif not widget.styleSheet():
            widget.setStyleSheet(STOCK_NATIVE_LINE_EDIT_QSS)

    for widget in root.findChildren(QTextEdit):
        if _has_stock_composite_ancestor(widget):
            continue
        if not widget.styleSheet():
            widget.setStyleSheet(STOCK_TEXT_EDIT_QSS)

    for widget in root.findChildren(QComboBox):
        if _has_stock_composite_ancestor(widget):
            continue
        if widget.objectName() == "Combo":
            continue
        if not widget.styleSheet():
            widget.setStyleSheet(STOCK_COMBO_QSS)

    for widget in root.findChildren(QDoubleSpinBox):
        if _has_stock_composite_ancestor(widget):
            continue
        if not widget.styleSheet():
            widget.setStyleSheet(STOCK_DOUBLE_SPIN_QSS)


def _apply_stock_composite_theme(root: QWidget | None) -> None:
    if root is None:
        return

    _apply_stock_native_field_theme(root)

    for widget in root.findChildren(SwitchSelectWidget):
        try:
            widget.setStyleSheet(STOCK_SWITCH_SELECT_QSS)
            popup = getattr(widget, "_popup", None)
            if popup is not None:
                popup.setStyleSheet(STOCK_SWITCH_SELECT_QSS)
        except Exception:
            pass

    for widget in root.findChildren(FileBadgePicker):
        try:
            widget.setStyleSheet(STOCK_FILE_BADGE_PICKER_QSS)
        except Exception:
            pass

    for widget in root.findChildren(NumberStepper):
        try:
            widget.setStyleSheet(STOCK_NUMBER_STEPPER_QSS)
        except Exception:
            pass


def _set_row(table: QTableWidget, row: int, col: int, text: str):
    it = QTableWidgetItem(text)
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    table.setItem(row, col, it)


def _fmt_num(val: Any, default: str = "0") -> str:
    try:
        num = float(val)
        if num.is_integer():
            return str(int(num))
        # trim trailing zeros for cleaner display
        s = f"{num:.3f}".rstrip("0").rstrip(".")
        return s if s else default
    except Exception:
        return default


def _same_display_cost(left: Any, right: Any) -> bool:
    return _fmt_num(left, default="") == _fmt_num(right, default="")


def _human_item_type(val: Any) -> str:
    s = str(val or "")
    if s == StockItemType.physical.value:
        return "Fiziki"
    if s == StockItemType.service.value:
        return "Hizmet"
    if s == StockItemType.digital.value:
        return "Dijital"
    if s == StockItemType.other.value:
        return "Diğer"
    if "physical" in s:
        return "Fiziki"
    if "service" in s:
        return "Hizmet"
    if "digital" in s:
        return "Dijital"
    if "other" in s:
        return "Diğer"
    return s



def _human_tx_direction(val: Any) -> str:
    s = str(val or "")
    if s.endswith("IN_") or s == "IN":
        return "Giriş"
    if s.endswith("OUT") or s == "OUT":
        return "Çıkış"
    return s


def _human_tx_reason(val: Any) -> str:
    s = str(val or "")
    if s.endswith("manual_in") or s == "manual_in":
        return "Manuel Giriş"
    if s.endswith("manual_out") or s == "manual_out":
        return "Manuel Çıkış"
    if s.endswith("adjustment") or s == "adjustment":
        return "Düzeltme"
    if s.endswith("return_in") or s == "return_in":
        return "İade Giriş"
    if s.endswith("order_out") or s == "order_out":
        return "Sipariş Çıkış"
    return s


def _human_unit_cost_input_mode(mode: Any, vat_rate: Any = None) -> str:
    raw = str(mode or "").strip().casefold()
    try:
        vat_text = f" %{float(vat_rate):g}" if vat_rate not in (None, "") else ""
    except Exception:
        vat_text = ""
    if raw == "gross":
        return "KDV dahil maliyet"
    if raw == "net":
        return f"KDV hariç maliyet{vat_text}".strip()
    if raw == "mixed_explicit":
        return "KDV dahil/hariç karma maliyet"
    if raw == "legacy":
        return "Eski kayıt brüt varsayımı"
    return ""


def _unit_cost_value_for_display(unit_cost: Any, *, input_mode: Any, vat_rate: Any = None) -> Optional[float]:
    try:
        amount = float(unit_cost)
    except Exception:
        return None

    normalized_mode = str(input_mode or "").strip().casefold()
    if normalized_mode != "net":
        return amount

    try:
        vat_value = float(vat_rate)
    except Exception:
        return amount

    divisor = 1.0 + (vat_value / 100.0)
    if vat_value < 0 or divisor <= 0:
        return amount
    return amount / divisor


def _tx_unit_cost_text(tx: Any) -> str:
    unit_cost = getattr(tx, "unit_cost", None)
    if unit_cost is None:
        return "-"

    display_value = _unit_cost_value_for_display(
        unit_cost,
        input_mode=getattr(tx, "unit_cost_input_mode", None),
        vat_rate=getattr(tx, "unit_cost_vat_rate", None),
    )
    currency = str(getattr(tx, "currency", "") or "").strip()
    cost_text = _fmt_num(display_value if display_value is not None else unit_cost, default="-")
    if currency:
        cost_text = f"{cost_text} {currency}"
    input_mode_text = _human_unit_cost_input_mode(
        getattr(tx, "unit_cost_input_mode", None),
        getattr(tx, "unit_cost_vat_rate", None),
    )
    if input_mode_text:
        cost_text = f"{cost_text} ({input_mode_text})"
    return cost_text


def _extract_order_number_from_note(note: Any) -> str:
    text = str(note or "").strip()
    if not text:
        return ""
    lower_text = text.lower()
    marker = "order:"
    idx = lower_text.find(marker)
    if idx < 0:
        return ""
    raw = text[idx + len(marker):]
    if "|" in raw:
        raw = raw.split("|", 1)[0]
    return str(raw or "").strip()


def _extract_listing_id_from_note(note: Any) -> str:
    text = str(note or "").strip()
    if not text:
        return ""
    lower_text = text.lower()
    marker = "listing:"
    idx = lower_text.find(marker)
    if idx < 0:
        return ""
    raw = text[idx + len(marker):]
    if "|" in raw:
        raw = raw.split("|", 1)[0]
    return str(raw or "").strip()


def _extract_order_number_from_tx(tx: Any) -> str:
    if tx is None:
        return ""
    order_ref = str(getattr(tx, "order_ref", "") or "").strip()
    if order_ref:
        return order_ref
    ref_type = str(getattr(tx, "reference_type", "") or "").strip().lower()
    ref_id = str(getattr(tx, "reference_id", "") or "").strip()
    if ref_type == str(StockReferenceType.order.value) and ref_id and not ref_id.casefold().startswith("ordauto:"):
        return ref_id
    for attr in ("order_number", "order_no", "orderNumber"):
        value = str(getattr(tx, attr, "") or "").strip()
        if value:
            return value
    return _extract_order_number_from_note(getattr(tx, "note", ""))


def _extract_listing_id_from_tx(tx: Any) -> str:
    if tx is None:
        return ""
    listing_id = str(getattr(tx, "listing_id", "") or "").strip()
    if listing_id:
        return listing_id
    return _extract_listing_id_from_note(getattr(tx, "note", ""))


def _clean_tx_note_for_card(note: Any) -> str:
    text = str(note or "").strip()
    if not text:
        return ""

    parts = [str(part or "").strip() for part in text.split("|") if str(part or "").strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]

    hidden_keys = {
        "order",
        "order ref",
        "order_ref",
        "siparis ref",
        "sipariş ref",
        "siparis_ref",
        "sipariş_ref",
        "listing",
        "ilan",
        "map qty",
        "map_qty",
    }

    kept_parts: list[str] = []
    for part in parts:
        if ":" not in part:
            kept_parts.append(part)
            continue
        key, _value = part.split(":", 1)
        normalized = str(key or "").strip().lower().replace("-", " ").replace("_", " ")
        if normalized in hidden_keys:
            continue
        kept_parts.append(part)

    return " | ".join(kept_parts).strip()


def _is_order_out_tx(tx: Any) -> bool:
    if tx is None:
        return False
    reason = str(getattr(tx, "reason", "") or "").lower().strip()
    return reason.endswith("order_out") or reason == "order_out"


def _has_listing_ref_tx(tx: Any) -> bool:
    return bool(_extract_listing_id_from_tx(tx))


def _first_image_path(value: Any) -> str:
    if not value:
        return ""

    candidates: list[str] = []
    if isinstance(value, list):
        candidates = [str(v or "").strip() for v in value]
    else:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                candidates = [str(v or "").strip() for v in parsed]
            elif isinstance(parsed, str):
                candidates = [parsed.strip()]
            else:
                candidates = [raw]
        except Exception:
            candidates = [raw]

    for path in candidates:
        if path:
            return path
    return ""






class FullscreenDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StockRoot")
        self.setStyleSheet(MODERN_LIGHT_QSS)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setModal(True)
        self.setSizeGripEnabled(True)

    def open_full(self):
        self.showMaximized()
        self.raise_()
        self.activateWindow()
        return self

    # ? native messageboxes: ghost olmaz
    def info(self, title: str, text: str):
        AppMessageCenter.info(self, title, text)

    def error(self, title: str, text: str):
        AppMessageCenter.error(self, title, text)

    def confirm(self, title: str, text: str) -> bool:
        return AppMessageCenter.confirm(self, title, text, default_yes=False)


# =========================================================
# ? StockTab (Dashboard)
# =========================================================

def _load_stock_items_snapshot() -> dict[str, Any]:
    items_result = action_list_items(only_active=False)
    balances_result = action_list_item_balances(warehouse_id=None, only_active=False)
    return {
        "items_result": items_result,
        "balances_result": balances_result,
    }









class StockTab(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StockRoot")
        self.setStyleSheet(MODERN_LIGHT_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        header = DashboardHeroCard(
            title="Envanter / Stok Yönetimi",
            subtitle="Stok kartları • Depolar • Giriş/Çıkış • Anlık durum",
            action_text="Anlık Durum",
        )
        if header.action_button is not None:
            header.action_button.clicked.connect(self.open_overview)
        root.addWidget(header)

        wrap = QuickAccessSection(
            title="Hızlı Erişim",
            subtitle="Stok kartları, hareketler ve grup tanımlarını ayrı pencerede aç.",
        )
        wl = wrap.body_layout

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.btn_items = self._build_quick_access_button("Stok Kartları", "stock-cards-icon.png")
        self.btn_tx = self._build_quick_access_button("Stok Giriş/Çıkış", "stock-in-out.png")
        self.btn_warehouses = self._build_quick_access_button("Depolar", "depo-icon.png")
        self.btn_upper_groups = self._build_quick_access_button("Üst Gruplar", "stock-upper-groups-icon.png")
        self.btn_sub_groups = self._build_quick_access_button("Alt Gruplar", "stock-sub-groups-icon.png")
        self.btn_items.clicked.connect(self.open_items)
        self.btn_tx.clicked.connect(self.open_tx)
        self.btn_warehouses.clicked.connect(self.open_warehouses)
        self.btn_upper_groups.clicked.connect(self.open_upper_groups)
        self.btn_sub_groups.clicked.connect(self.open_sub_groups)

        grid.addWidget(self.btn_items, 0, 0)
        grid.addWidget(self.btn_tx, 0, 1)
        grid.addWidget(self.btn_warehouses, 0, 2)
        grid.addWidget(self.btn_upper_groups, 1, 0)
        grid.addWidget(self.btn_sub_groups, 1, 1)

        wl.addLayout(grid)
        root.addWidget(wrap)
        root.addStretch(1)

        self._quick_badges = {
            "items": 0,
            "tx": 0,
            "warehouses": 0,
            "upper_groups": 0,
            "sub_groups": 0,
        }
        self._quick_open_sections: set[str] = set()
        self._open_dialogs: list[QDialog] = []
        stock_signals.quick_access_changed.connect(self._on_quick_access_changed)
        self._apply_quick_access_badges()

    def _build_quick_access_button(self, text: str, icon_name: str) -> BadgeButton:
        icon_file = ASSETS_DIR / icon_name
        icon_path = str(icon_file) if icon_file.exists() else None
        btn = BadgeButton(
            text,
            icon_path=icon_path,
            icon_size=48,
            size_scale=1.6632,
        )
        btn.setMinimumHeight(100)
        btn.setBadgeCount(0)
        return btn

    @staticmethod
    def _normalize_quick_key(key: Any) -> Optional[str]:
        raw = str(key or "").strip().lower()
        if raw in {"item", "items", "stock_item", "stock_items"}:
            return "items"
        if raw in {"tx", "transaction", "transactions", "stock_tx", "stock_txs"}:
            return "tx"
        if raw in {"warehouse", "warehouses"}:
            return "warehouses"
        if raw in {"upper_group", "upper_groups", "ust_grup", "ust_gruplar"}:
            return "upper_groups"
        if raw in {"sub_group", "sub_groups", "subgroup", "subgroups", "alt_grup", "alt_gruplar"}:
            return "sub_groups"
        return None

    def _apply_quick_access_badges(self) -> None:
        self.btn_items.setBadgeCount(int(self._quick_badges.get("items", 0)))
        self.btn_tx.setBadgeCount(int(self._quick_badges.get("tx", 0)))
        self.btn_warehouses.setBadgeCount(int(self._quick_badges.get("warehouses", 0)))
        self.btn_upper_groups.setBadgeCount(int(self._quick_badges.get("upper_groups", 0)))
        self.btn_sub_groups.setBadgeCount(int(self._quick_badges.get("sub_groups", 0)))

    def _clear_quick_badge(self, key: str) -> None:
        norm = self._normalize_quick_key(key)
        if not norm:
            return
        self._quick_badges[norm] = 0
        self._apply_quick_access_badges()

    def _on_quick_access_changed(self, section: str, delta: int) -> None:
        norm = self._normalize_quick_key(section)
        if not norm:
            return
        if norm in self._quick_open_sections:
            self._quick_badges[norm] = 0
        else:
            add = max(1, int(delta or 1))
            self._quick_badges[norm] = max(0, int(self._quick_badges.get(norm, 0)) + add)
        self._apply_quick_access_badges()

    def _mark_quick_section_open(self, key: str, dialog: QDialog) -> None:
        norm = self._normalize_quick_key(key)
        if not norm:
            return
        self._quick_open_sections.add(norm)
        self._clear_quick_badge(norm)

        def _on_closed(_obj=None):
            self._quick_open_sections.discard(norm)
            self._clear_quick_badge(norm)

        dialog.finished.connect(lambda _code=0: _on_closed())
        dialog.destroyed.connect(_on_closed)

    def _retain_open_dialog(self, dialog: QDialog) -> None:
        self._open_dialogs.append(dialog)

        def _release(_obj=None, dlg=dialog):
            try:
                self._open_dialogs.remove(dlg)
            except ValueError:
                pass

        dialog.finished.connect(lambda _code=0, dlg=dialog: _release(dlg))
        dialog.destroyed.connect(lambda _obj=None, dlg=dialog: _release(dlg))

    def _open_full_dialog(
        self,
        dialog_cls,
        dialog_name: str,
        quick_key: Optional[str] = None,
        quick_icon_name: Optional[str] = None,
    ):
        try:
            dlg = dialog_cls(self)
            if quick_icon_name:
                icon_file = ASSETS_DIR / str(quick_icon_name)
                if icon_file.exists():
                    dlg.setWindowIcon(QIcon(str(icon_file)))
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._retain_open_dialog(dlg)
            if quick_key:
                self._mark_quick_section_open(quick_key, dlg)
            dlg.open_full()
        except Exception as e:
            AppMessageCenter.error(self, "Hata", f"{dialog_name} açılamadı.\n{e}")

    def open_items(self):
        self._open_full_dialog(
            __getattr__("StockItemManagerDialog"),
            "Stok Kartları",
            quick_key="items",
            quick_icon_name="stock-cards-icon.png",
        )

    def open_tx(self):
        self._open_full_dialog(
            __getattr__("StockTxDialog"),
            "Stok Giriş/Çıkış",
            quick_key="tx",
            quick_icon_name="stock-in-out.png",
        )

    def open_warehouses(self):
        self._open_full_dialog(
            __getattr__("WarehouseManagerDialog"),
            "Depolar",
            quick_key="warehouses",
            quick_icon_name="depo-icon.png",
        )

    def open_upper_groups(self):
        self._open_full_dialog(
            __getattr__("UpperGroupManagerDialog"),
            "Üst Gruplar",
            quick_key="upper_groups",
            quick_icon_name="stock-upper-groups-icon.png",
        )

    def open_sub_groups(self):
        self._open_full_dialog(
            __getattr__("SubGroupManagerDialog"),
            "Alt Gruplar",
            quick_key="sub_groups",
            quick_icon_name="stock-sub-groups-icon.png",
        )

    def open_overview(self):
        self._open_full_dialog(__getattr__("StockOverviewDialog"), "Anlık Durum")


_WINDOW_EXPORTS = {
    "StockItemsListModel": ".stock_item_manager_dialog",
    "StockItemsListDelegate": ".stock_item_manager_dialog",
    "StockItemsListWidget": ".stock_item_manager_dialog",
    "StockItemsWorkspaceBehaviorAdapter": ".stock_item_manager_dialog",
    "StockTxListModel": ".stock_tx_dialog",
    "StockTxListDelegate": ".stock_tx_dialog",
    "StockTxListWidget": ".stock_tx_dialog",
    "StockTxWorkspaceBehaviorAdapter": ".stock_tx_dialog",
    "ManagerCardsListModel": ".company_manager_dialog",
    "ManagerCardsListDelegate": ".company_manager_dialog",
    "ManagerCardsListWidget": ".company_manager_dialog",
    "StockManagerWorkspaceBehaviorAdapter": ".company_manager_dialog",
    "SubGroupWorkspaceBehaviorAdapter": ".sub_group_manager_dialog",
    "UpperGroupWorkspaceBehaviorAdapter": ".upper_group_manager_dialog",
    "StockItemManagerDialog": ".stock_item_manager_dialog",
    "WarehouseManagerDialog": ".warehouse_manager_dialog",
    "SubGroupManagerDialog": ".sub_group_manager_dialog",
    "UpperGroupManagerDialog": ".upper_group_manager_dialog",
    "BrandManagerDialog": ".brand_manager_dialog",
    "CompanyManagerDialog": ".company_manager_dialog",
    "StockTxDialog": ".stock_tx_dialog",
    "StockOverviewDialog": ".stock_overview_dialog",
}


def __getattr__(name: str):
    module_name = _WINDOW_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name, __package__), name)
    globals()[name] = value
    return value


__all__ = [name for name in globals() if not name.startswith("__")]




