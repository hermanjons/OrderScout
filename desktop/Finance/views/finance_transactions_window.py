from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from PyQt6.QtCore import QDate, Qt, QSignalBlocker, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from Core.threads.sync_worker import SyncWorker
from Core.constants.time_constants import TZ_GMT3
from Core.views import (
    DateSelector,
    RECORD_WORKSPACE_STYLE as FINANCE_STYLE,
    RecordWorkspaceBehaviorAdapter,
    RecordWorkspaceCardRecord,
    RecordWorkspaceListWidget,
    RecordWorkspaceScaffold,
    optimized_table_updates,
)
from Feedback.processors.pipeline import MessageHandler, Result
from Finance.constants.ui_constants import (
    FINANCE_TRANSACTION_ALL_TEXT,
    FINANCE_TRANSACTION_COMPANY_LABEL,
    FINANCE_TRANSACTION_DATE_RANGE_LABEL,
    FINANCE_TRANSACTION_DETAIL_HINT,
    FINANCE_TRANSACTION_DETAIL_TITLE,
    FINANCE_TRANSACTION_EMPTY_TEXT,
    FINANCE_TRANSACTION_FILTER_INFO_TEMPLATE,
    FINANCE_TRANSACTION_FILTERS_SUBTITLE,
    FINANCE_TRANSACTION_RECORDS_SUBTITLE,
    FINANCE_TRANSACTION_RECORDS_SUMMARY_TEMPLATE,
    FINANCE_TRANSACTION_RECORDS_TITLE,
    FINANCE_TRANSACTION_RESET_FILTERS_TEXT,
    FINANCE_TRANSACTION_SEARCH_PLACEHOLDER,
    FINANCE_TRANSACTION_SERVICE_LABEL,
    FINANCE_TRANSACTION_TYPE_LABEL,
    FINANCE_TRANSACTION_WINDOW_TITLE,
)
from settings import ASSETS_DIR


def _trendyol_finance_default_fetch_days() -> int:
    from Finance.constants.trendyol.constants import TRENDYOL_FINANCE_DEFAULT_FETCH_DAYS

    return int(TRENDYOL_FINANCE_DEFAULT_FETCH_DAYS)


def _finance_default_date_range():
    today = datetime.now(TZ_GMT3).date()
    start = today - timedelta(days=max(1, _trendyol_finance_default_fetch_days()) - 1)
    return start, today


def _load_finance_transactions_from_db(**kwargs):
    from Finance.views.actions import load_finance_transactions_from_db

    return load_finance_transactions_from_db(**kwargs)


def _save_manual_finance_transaction(payload: dict):
    from Finance.views.actions import save_manual_finance_transaction

    return save_manual_finance_transaction(payload)


@dataclass
class FinanceTransactionWorkspaceRecord(RecordWorkspaceCardRecord):
    @classmethod
    def from_row(cls, record: dict) -> "FinanceTransactionWorkspaceRecord":
        payload = dict(record or {})
        tx_type = str(payload.get("transactionType") or "-")
        order_no = str(payload.get("orderNumber") or "-")
        invoice_no = str(payload.get("commissionInvoiceSerialNumber") or "-")
        source_label = str(payload.get("sourceLabel") or payload.get("serviceLabel") or payload.get("serviceKey") or "-")
        direction = str(payload.get("directionText") or "-")
        related_cargo = int(payload.get("relatedCargoItemCount") or 0)
        cargo_text = f" | Kargo Kalemi: {related_cargo}" if related_cargo > 0 else ""
        return cls(
            orderNumber=str(payload.get("recordKey") or ""),
            title=f"{payload.get('transactionDateText') or '-'} | {tx_type}",
            subtitle=(
                f"{payload.get('companyName') or '-'} | "
                f"{source_label}"
            ),
            extra=(
                f"Yön: {direction} | "
                f"Net: {payload.get('netAmountText', '0.00')} {payload.get('currency') or 'TRY'} | "
                f"Borç: {payload.get('debtText', '0.00')} | "
                f"Alacak: {payload.get('creditText', '0.00')} | "
                f"Sipariş: {order_no} | Fatura: {invoice_no}"
                f"{cargo_text}"
            ),
            logo_path=str(ASSETS_DIR / "finance-transactions-icon.png"),
            payload=payload,
        )


class FinanceTransactionListWidget(RecordWorkspaceListWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, empty_placeholder_text=FINANCE_TRANSACTION_EMPTY_TEXT)


class FinanceTransactionsWorkspaceAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, window: "FinanceTransactionsWindow") -> None:
        self.window = window
        self.new_panel_id = "new"
        self.edit_panel_id = "detail"
        self.bulk_panel_id = None
        self.clear_active_on_close = True

    @property
    def list_widget(self):
        return self.window.list_widget

    def get_mode(self) -> str:
        return str(self.window._mode or "edit")

    def set_mode(self, mode: str) -> None:
        self.window._mode = str(mode or "edit").strip().lower() or "edit"

    def get_active_key(self) -> str:
        return str(self.window._selected_record_key or "")

    def get_selected_count(self) -> int:
        return 0

    def get_record_key(self, record) -> str:
        payload = getattr(record, "payload", None) or {}
        return str(payload.get("recordKey") or getattr(record, "recordKey", "") or "")

    def prepare_new(self) -> None:
        self.window._prepare_new_manual_record()

    def activate_record(self, record) -> None:
        self.window._mode = "edit"
        self.window._workspace_activate_record(record)

    def clear_active(self) -> None:
        self.window._workspace_clear_active_record()

    def apply_selection(self, record, selected: bool) -> None:
        _ = record
        _ = selected

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        _ = enabled

    def on_state_changed(self) -> None:
        self.window._sync_workspace_state()

    def open_panel(self, shell) -> None:
        _ = shell
        self.window._open_detail_panel()

    def close_panel(self, shell) -> None:
        _ = shell
        self.window._mode = "edit"
        self.window._close_detail_panel()

    def edit_guidance_message(self) -> str:
        return FINANCE_TRANSACTION_DETAIL_HINT

    def bulk_guidance_message(self) -> str:
        return ""


class FinanceTransactionsWindow(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("FinanceRoot")
        self.setStyleSheet(FINANCE_STYLE)
        self.setWindowTitle(FINANCE_TRANSACTION_WINDOW_TITLE)
        self.setWindowIcon(QIcon(os.path.join(ASSETS_DIR, "finance-transactions-icon.png")))
        self.setGeometry(220, 120, 1500, 860)

        self._suspend_reload = False
        self._has_loaded_once = False
        self._all_records: list[dict] = []
        self._record_map: dict[str, dict] = {}
        self._selected_record_key = ""
        self._mode = "edit"
        self._left_stick_size = 520
        self._reload_worker: SyncWorker | None = None
        self._reload_pending = False
        self._reload_seq = 0

        self._search_timer = QTimer(self)
        self._search_timer.setInterval(250)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.reload_from_db)

        self._workspace = RecordWorkspaceScaffold(
            self,
            empty_placeholder_text=FINANCE_TRANSACTION_EMPTY_TEXT,
            left_title=FINANCE_TRANSACTION_DETAIL_TITLE,
            left_subtitle=FINANCE_TRANSACTION_DETAIL_HINT,
            filters_title="Filtreler",
            filters_subtitle=FINANCE_TRANSACTION_FILTERS_SUBTITLE,
            records_title=FINANCE_TRANSACTION_RECORDS_TITLE,
            records_subtitle=FINANCE_TRANSACTION_RECORDS_SUBTITLE,
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": "Manuel finans hareketi ekle",
                    "icon_path": str(ASSETS_DIR / "yeni-kayit.png"),
                    "shape": "circular",
                    "icon_scale": 1.18,
                },
                {
                    "panel_id": "detail",
                    "text": "",
                    "tooltip": "Hareket detay paneli",
                    "icon_path": str(ASSETS_DIR / "duzenleme-icon.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
            ),
            shell_kwargs={
                "sidebar_width": 92,
                "left_stick_size": self._left_stick_size,
                "left_collapse_trigger": 520,
                "min_left_width": 420,
                "min_right_width": 320,
                "root_margins": (0, 0, 0, 0),
                "root_spacing": 8,
                "snap_on_drag": False,
            },
            page_size_options=(20, 50, 100),
            style_sheet=FINANCE_STYLE,
            show_editor_actions_card=False,
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._workspace)

        self._workspace_shell = self._workspace.shell
        self.left_panel_title = self._workspace.left_card.title_label
        self.left_panel_hint = self._workspace.left_card.subtitle_label

        self.editor_stack = QStackedWidget(self)
        self.manual_form: QWidget | None = None

        self.detail_card = QWidget(self)
        detail_layout = QVBoxLayout(self.detail_card)
        detail_layout.setContentsMargins(14, 12, 14, 12)
        detail_layout.setSpacing(10)

        self.detail_empty_label = QLabel(FINANCE_TRANSACTION_DETAIL_HINT, objectName="Muted")
        self.detail_empty_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_empty_label)

        info_grid = QGridLayout()
        info_grid.setContentsMargins(0, 0, 0, 0)
        info_grid.setHorizontalSpacing(10)
        info_grid.setVerticalSpacing(8)
        self._detail_fields: dict[str, QLabel] = {}
        detail_rows = [
            ("transactionDateText", "Tarih"),
            ("sourceLabel", "Kaynak"),
            ("companyName", FINANCE_TRANSACTION_COMPANY_LABEL),
            ("serviceLabel", FINANCE_TRANSACTION_SERVICE_LABEL),
            ("transactionType", FINANCE_TRANSACTION_TYPE_LABEL),
            ("directionText", "Yön"),
            ("orderNumber", "Sipariş No"),
            ("commissionInvoiceSerialNumber", "Fatura Seri"),
            ("debtText", "Borç"),
            ("creditText", "Alacak"),
            ("netAmountText", "Net"),
            ("currency", "Para Birimi"),
        ]
        for idx, (field_key, title) in enumerate(detail_rows):
            host = QFrame(self.detail_card)
            item_layout = QVBoxLayout(host)
            item_layout.setContentsMargins(10, 8, 10, 8)
            item_layout.setSpacing(2)
            host.setObjectName("DetailMetricCard")
            item_layout.addWidget(QLabel(title, objectName="DetailCaption"))
            value_label = QLabel("-", objectName="DetailValue")
            value_label.setWordWrap(True)
            item_layout.addWidget(value_label)
            self._detail_fields[field_key] = value_label
            info_grid.addWidget(host, idx // 2, idx % 2)
        detail_layout.addLayout(info_grid)

        detail_layout.addWidget(QLabel("Kayıt Alanları", objectName="SectionTitle"))
        self.detail_table = self._make_table(["Alan", "Değer"], min_height=300)
        detail_layout.addWidget(self.detail_table, 1)
        self.editor_stack.addWidget(self.detail_card)
        self.editor_stack.setCurrentWidget(self.detail_card)
        self._workspace.set_editor_widget(self.editor_stack)

        filters_host = QWidget(self)
        filter_layout = QVBoxLayout(filters_host)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addStretch(1)
        self.btn_reset = QPushButton(FINANCE_TRANSACTION_RESET_FILTERS_TEXT)
        self.btn_reset.setObjectName("SoftDanger")
        self.btn_reset.clicked.connect(self._reset_filters)
        top_row.addWidget(self.btn_reset)
        filter_layout.addLayout(top_row)

        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("Input")
        self.search_input.setPlaceholderText(FINANCE_TRANSACTION_SEARCH_PLACEHOLDER)
        self.search_input.textChanged.connect(self._schedule_reload)
        filter_layout.addWidget(self.search_input)

        filter_grid = QGridLayout()
        filter_grid.setContentsMargins(0, 0, 0, 0)
        filter_grid.setHorizontalSpacing(10)
        filter_grid.setVerticalSpacing(8)

        self.company_combo = QComboBox(self)
        self.company_combo.setObjectName("Combo")
        self.company_combo.currentIndexChanged.connect(self.reload_from_db)
        self.service_combo = QComboBox(self)
        self.service_combo.setObjectName("Combo")
        self.service_combo.currentIndexChanged.connect(self.reload_from_db)
        self.transaction_type_combo = QComboBox(self)
        self.transaction_type_combo.setObjectName("Combo")
        self.transaction_type_combo.currentIndexChanged.connect(self.reload_from_db)

        self.date_range = DateSelector(range_enabled=True)
        self.date_range.rangeChanged.connect(lambda *_: self.reload_from_db())
        start_default, end_default = _finance_default_date_range()
        self.date_range.setRange(
            QDate(start_default.year, start_default.month, start_default.day),
            QDate(end_default.year, end_default.month, end_default.day),
        )

        filter_grid.addWidget(QLabel(FINANCE_TRANSACTION_COMPANY_LABEL, objectName="Muted"), 0, 0)
        filter_grid.addWidget(self.company_combo, 1, 0)
        filter_grid.addWidget(QLabel(FINANCE_TRANSACTION_SERVICE_LABEL, objectName="Muted"), 0, 1)
        filter_grid.addWidget(self.service_combo, 1, 1)
        filter_grid.addWidget(QLabel(FINANCE_TRANSACTION_TYPE_LABEL, objectName="Muted"), 0, 2)
        filter_grid.addWidget(self.transaction_type_combo, 1, 2)
        filter_grid.addWidget(QLabel(FINANCE_TRANSACTION_DATE_RANGE_LABEL, objectName="Muted"), 0, 3)
        filter_grid.addWidget(self.date_range, 1, 3)
        filter_layout.addLayout(filter_grid)

        self.filter_info_label = QLabel(
            FINANCE_TRANSACTION_FILTER_INFO_TEMPLATE.format(
                company=FINANCE_TRANSACTION_ALL_TEXT,
                service=FINANCE_TRANSACTION_ALL_TEXT,
                transaction_type=FINANCE_TRANSACTION_ALL_TEXT,
            ),
            objectName="StatusInfo",
        )
        self.filter_info_label.setWordWrap(True)
        filter_layout.addWidget(self.filter_info_label)

        self.summary_label = QLabel("Toplam hareket: 0", objectName="StatusInfo")
        self.summary_label.setWordWrap(True)
        filter_layout.addWidget(self.summary_label)
        self._workspace.set_filters_widget(filters_host)

        self.list_widget = FinanceTransactionListWidget(self._workspace.records_card)
        self.list_widget.page_changed.connect(lambda *_args: self._sync_workspace_summary())
        self._workspace.set_list_widget(self.list_widget)
        self._workspace.footer_bar.select_toggle.hide()
        self._workspace_shell.close_left_panel()
        self._workspace.set_records_summary_text(
            FINANCE_TRANSACTION_RECORDS_SUMMARY_TEMPLATE.format(shown=0, total=0)
        )

        self._workspace_adapter = FinanceTransactionsWorkspaceAdapter(self)
        self._workspace_controller = self._workspace.create_behavior_controller(adapter=self._workspace_adapter)
        self._set_detail_record(None)

    def _build_manual_form(self) -> QWidget:
        from PyQt6.QtWidgets import QPlainTextEdit

        from Core.views import FileBadgePicker
        from Finance.constants.domain_constants import FINANCE_CURRENCY_OPTIONS

        form = QWidget(self)
        layout = QVBoxLayout(form)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Manuel Finans Hareketi", objectName="SectionTitle"))
        hint = QLabel("Kira, paketleme, banka masrafı veya pazaryeri dışı gelir/giderleri buradan kaydet.", objectName="Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.manual_direction = QComboBox(self)
        self.manual_direction.setObjectName("Combo")
        self.manual_direction.addItem("Gider / Borç", "expense")
        self.manual_direction.addItem("Gelir / Alacak", "income")

        self.manual_date = DateSelector()
        self.manual_date.setDate(QDate.currentDate())

        self.manual_amount = QLineEdit(self)
        self.manual_amount.setObjectName("Input")
        self.manual_amount.setPlaceholderText("Örn. 1250,00")

        self.manual_currency = QComboBox(self)
        self.manual_currency.setObjectName("Combo")
        for code in FINANCE_CURRENCY_OPTIONS:
            self.manual_currency.addItem(str(code), str(code))
        try_idx = self.manual_currency.findText("TRY")
        self.manual_currency.setCurrentIndex(try_idx if try_idx >= 0 else 0)

        self.manual_category = QLineEdit(self)
        self.manual_category.setObjectName("Input")
        self.manual_category.setPlaceholderText("Örn. Dükkan Kirası")

        self.manual_counterparty = QLineEdit(self)
        self.manual_counterparty.setObjectName("Input")
        self.manual_counterparty.setPlaceholderText("Firma / kişi")

        self.manual_reference = QLineEdit(self)
        self.manual_reference.setObjectName("Input")
        self.manual_reference.setPlaceholderText("Makbuz, dekont veya referans no")

        self.manual_payment_method = QLineEdit(self)
        self.manual_payment_method.setObjectName("Input")
        self.manual_payment_method.setPlaceholderText("Nakit, banka, kart...")

        fields = [
            ("Yön", self.manual_direction),
            ("Tarih", self.manual_date),
            ("Tutar", self.manual_amount),
            ("Para Birimi", self.manual_currency),
            ("Kategori", self.manual_category),
            ("Muhatap", self.manual_counterparty),
            ("Referans", self.manual_reference),
            ("Ödeme Şekli", self.manual_payment_method),
        ]
        for idx, (label, widget) in enumerate(fields):
            grid.addWidget(QLabel(label, objectName="Muted"), idx, 0)
            grid.addWidget(widget, idx, 1)
        layout.addLayout(grid)

        layout.addWidget(QLabel("Açıklama / Not", objectName="Muted"))
        self.manual_note = QPlainTextEdit(self)
        self.manual_note.setObjectName("Input")
        self.manual_note.setPlaceholderText("Hareketle ilgili kısa açıklama")
        self.manual_note.setMaximumHeight(86)
        layout.addWidget(self.manual_note)

        self.manual_files = FileBadgePicker(
            self,
            button_text="Belge Ekle",
            dialog_title="Finans hareketi belgesi seç",
            dialog_filter="Belgeler (*.pdf *.png *.jpg *.jpeg *.webp *.xml *.html);;Tüm Dosyalar (*)",
            allowed_extensions=[".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xml", ".html"],
            allow_multiple=True,
            show_clear_button=True,
        )
        layout.addWidget(self.manual_files)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.btn_manual_clear = QPushButton("Temizle")
        self.btn_manual_clear.setObjectName("SoftDanger")
        self.btn_manual_clear.clicked.connect(self._clear_manual_form)
        self.btn_manual_save = QPushButton("Kaydet")
        self.btn_manual_save.setObjectName("Primary")
        self.btn_manual_save.clicked.connect(self._save_manual_form)
        button_row.addWidget(self.btn_manual_clear)
        button_row.addWidget(self.btn_manual_save)
        layout.addLayout(button_row)
        layout.addStretch(1)
        return form

    @staticmethod
    def _make_table(headers: list[str], *, min_height: int) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(min_height)
        table.setHorizontalHeaderLabels(headers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        return table

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._has_loaded_once:
            self._set_list_loading(True)
            QTimer.singleShot(0, self.reload_from_db)
            self._has_loaded_once = True

    def _set_list_loading(self, busy: bool, message: str = "Finans hareketleri yükleniyor...") -> None:
        self._workspace.set_list_loading(bool(busy), message=message)
        self._workspace.sync_list_loading_geometry()

    def _open_detail_panel(self) -> None:
        self._workspace_shell.open_left_panel(left_width=self._left_stick_size, min_left=420, min_right=320)

    def _close_detail_panel(self) -> None:
        self._workspace_shell.close_left_panel()

    def _prepare_new_manual_record(self) -> None:
        self._mode = "new"
        self._selected_record_key = ""
        self.list_widget.clear_active_record() if hasattr(self, "list_widget") else None
        if self.manual_form is None:
            self.manual_form = self._build_manual_form()
            self.editor_stack.insertWidget(0, self.manual_form)
        self.editor_stack.setCurrentWidget(self.manual_form)
        self._workspace.set_left_title("Manuel Finans Hareketi")
        self._workspace.set_left_subtitle("Pazaryeri dışı gelir/gider kaydı")
        self._clear_manual_form(reset_date=False)

    def _clear_manual_form(self, *, reset_date: bool = True) -> None:
        if self.manual_form is None:
            return
        self.manual_direction.setCurrentIndex(0)
        if reset_date:
            self.manual_date.setDate(QDate.currentDate())
        self.manual_amount.clear()
        self.manual_category.clear()
        self.manual_counterparty.clear()
        self.manual_reference.clear()
        self.manual_payment_method.clear()
        self.manual_note.clear()
        self.manual_files.clearFiles()
        idx = self.manual_currency.findText("TRY")
        self.manual_currency.setCurrentIndex(idx if idx >= 0 else 0)

    @staticmethod
    def _parse_amount_text(text: str) -> float | None:
        raw = str(text or "").strip().replace(" ", "")
        if not raw:
            return None
        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                raw = raw.replace(".", "").replace(",", ".")
            else:
                raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", ".")
        try:
            value = float(raw)
        except Exception:
            return None
        return value if value > 0 else None

    def _save_manual_form(self) -> None:
        amount = self._parse_amount_text(self.manual_amount.text())
        if amount is None:
            MessageHandler.show(self, Result.fail("Tutar sıfırdan büyük olmalı.", close_dialog=False), only_errors=True)
            return
        qdate = self.manual_date.date()
        payload = {
            "direction": self.manual_direction.currentData(),
            "transactionDate": qdate.toPyDate(),
            "amount": amount,
            "currency": self.manual_currency.currentText(),
            "categoryName": self.manual_category.text().strip() or None,
            "counterparty": self.manual_counterparty.text().strip() or None,
            "referenceNo": self.manual_reference.text().strip() or None,
            "paymentMethod": self.manual_payment_method.text().strip() or None,
            "description": self.manual_note.toPlainText().strip() or None,
            "attachments": self.manual_files.files(),
        }
        result = _save_manual_finance_transaction(payload)
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        self._clear_manual_form()
        self._mode = "edit"
        self.editor_stack.setCurrentWidget(self.detail_card)
        self.reload_from_db()
        MessageHandler.show(self, result, only_errors=False)

    def _schedule_reload(self) -> None:
        if self._suspend_reload:
            return
        self._search_timer.start()

    def _fill_combo(self, combo: QComboBox, items, current_value: str = "") -> None:
        with QSignalBlocker(combo):
            combo.clear()
            for item in list(items or []):
                if isinstance(item, tuple):
                    label, value = item[0], item[1]
                else:
                    label, value = item, item
                label_text = str(label or "").strip()
                value_text = str(value or "").strip()
                if label_text:
                    combo.addItem(label_text, value_text)
            if combo.count() == 0:
                combo.addItem(FINANCE_TRANSACTION_ALL_TEXT, "")
            idx = combo.findData(str(current_value or "").strip())
            combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _reset_filters(self) -> None:
        self._suspend_reload = True
        try:
            self.search_input.clear()
            self.company_combo.setCurrentIndex(0)
            self.service_combo.setCurrentIndex(0)
            self.transaction_type_combo.setCurrentIndex(0)
            start_default, end_default = _finance_default_date_range()
            self.date_range.setRange(
                QDate(start_default.year, start_default.month, start_default.day),
                QDate(end_default.year, end_default.month, end_default.day),
            )
        finally:
            self._suspend_reload = False
        self.reload_from_db()

    def _sync_filter_options(self, metadata: dict) -> None:
        current_company = str(self.company_combo.currentData() or "").strip()
        current_service = str(self.service_combo.currentData() or "").strip()
        current_type = str(self.transaction_type_combo.currentData() or "").strip()
        company_options = [(FINANCE_TRANSACTION_ALL_TEXT, "")] + [
            (str(item), str(item)) for item in list(metadata.get("company_names") or []) if str(item or "").strip()
        ]
        service_options = list(metadata.get("service_options") or [(FINANCE_TRANSACTION_ALL_TEXT, "")])
        type_options = [(str(item), "" if str(item) == FINANCE_TRANSACTION_ALL_TEXT else str(item)) for item in list(metadata.get("transaction_type_options") or [])]
        self._fill_combo(self.company_combo, company_options, current_company)
        self._fill_combo(self.service_combo, service_options, current_service)
        self._fill_combo(self.transaction_type_combo, type_options, current_type)

    def _sync_workspace_summary(self) -> None:
        total = len(self._all_records)
        shown = self.list_widget.shown_count()
        self._workspace.set_records_summary_text(
            FINANCE_TRANSACTION_RECORDS_SUMMARY_TEMPLATE.format(shown=shown, total=total)
        )
        self._workspace.set_filters_footer_text(self.summary_label.text())

    def _sync_workspace_state(self) -> None:
        if self._mode == "new":
            self._workspace.set_left_title("Manuel Finans Hareketi")
            self._workspace.set_left_subtitle("Pazaryeri dışı gelir/gider kaydı")
            self.list_widget.set_active_spin_allowed(False)
            self._sync_workspace_summary()
            return
        record = self._record_map.get(self._selected_record_key, {})
        if self._selected_record_key:
            self._workspace.set_left_title(str(record.get("transactionType") or FINANCE_TRANSACTION_DETAIL_TITLE))
            self._workspace.set_left_subtitle(
                f"{record.get('transactionDateText') or '-'} | {record.get('companyName') or '-'}"
            )
        else:
            self._workspace.set_left_title(FINANCE_TRANSACTION_DETAIL_TITLE)
            self._workspace.set_left_subtitle(FINANCE_TRANSACTION_DETAIL_HINT)
        self.list_widget.set_active_spin_allowed(bool(self._selected_record_key))
        self._sync_workspace_summary()

    def _workspace_clear_active_record(self) -> None:
        self._selected_record_key = ""
        self.list_widget.clear_active_record()
        self._set_detail_record(None)

    def _workspace_activate_record(self, record: FinanceTransactionWorkspaceRecord) -> None:
        payload = dict(getattr(record, "payload", {}) or {})
        record_key = str(payload.get("recordKey") or record.recordKey or "").strip()
        if not record_key:
            return
        self.list_widget.set_active_record(record)
        self._selected_record_key = record_key
        self._set_detail_record(self._record_map.get(record_key))

    def _set_detail_record(self, record: dict | None) -> None:
        if self._mode != "new":
            self.editor_stack.setCurrentWidget(self.detail_card)
        if not record:
            self.detail_empty_label.setVisible(True)
            for label in self._detail_fields.values():
                label.setText("-")
            self.detail_table.setRowCount(0)
            self._sync_workspace_state()
            return

        self.detail_empty_label.setVisible(False)
        for key, label in self._detail_fields.items():
            label.setText(str(record.get(key) or "-"))

        rows = [
            ("Kayıt ID", record.get("recordId")),
            ("Açıklama", record.get("description")),
            ("Referans", record.get("referenceText")),
            ("Kaynak Türü", record.get("sourceKind")),
            ("Muhatap", record.get("counterparty")),
            ("Kategori", record.get("categoryName")),
            ("Ödeme Şekli", record.get("paymentMethod")),
            ("Satıcı Hesabı", record.get("sellerAccountId")),
            ("Satıcı ID", record.get("sellerId")),
            ("Paket ID", record.get("shipmentPackageId")),
            ("Barkod", record.get("barcode")),
            ("Ödeme Emri", record.get("paymentOrderId")),
            ("Ödeme Periyodu", record.get("paymentPeriod")),
            ("Sipariş Tarihi", record.get("orderDateText")),
            ("Ödeme Tarihi", record.get("paymentDateText")),
            ("Satıcı Geliri", record.get("sellerRevenueText")),
            ("Komisyon Oranı", record.get("commissionRateText")),
            ("Komisyon Tutarı", record.get("commissionAmountText")),
            ("Mağaza", record.get("storeName")),
            ("Ülke", record.get("country")),
            ("Affiliate", record.get("affiliate")),
            ("Kargo Kalemi", record.get("relatedCargoItemCount")),
            ("Kargo Siparişi", record.get("relatedCargoOrderCount")),
            ("Kargo Toplamı", record.get("relatedCargoTotalAmountText")),
            ("Kargo Desi", record.get("relatedCargoTotalDesiText")),
            ("Kargo Siparişleri", record.get("relatedCargoOrdersText")),
            ("Ekler", record.get("attachmentsJson")),
            ("Not", record.get("note")),
        ]
        rows = [(label, "-" if value in (None, "") else str(value)) for label, value in rows]
        table = self.detail_table
        with optimized_table_updates(table, len(rows)):
            for row_idx, (label, value) in enumerate(rows):
                table.setItem(row_idx, 0, QTableWidgetItem(label))
                table.setItem(row_idx, 1, QTableWidgetItem(value))
        self._sync_workspace_state()

    def reload_from_db(self, *_args) -> None:
        if self._suspend_reload:
            return
        worker = self._reload_worker
        if worker is not None and worker.isRunning():
            self._reload_pending = True
            return
        self._reload_pending = False
        self._reload_seq += 1
        seq = int(self._reload_seq)
        self._set_list_loading(True)

        worker = SyncWorker(
            _load_finance_transactions_from_db,
            search_text=self.search_input.text().strip(),
            company_name=str(self.company_combo.currentData() or "").strip(),
            service_key=str(self.service_combo.currentData() or "").strip(),
            transaction_type=str(self.transaction_type_combo.currentData() or "").strip(),
            date_from=self.date_range.dateFrom().toPyDate(),
            date_to=self.date_range.dateTo().toPyDate(),
            parent=self,
        )
        self._reload_worker = worker

        def _handle_result(result) -> None:
            if seq != self._reload_seq:
                return
            if not result.success:
                self.summary_label.setText(f"Hata: {result.message}")
                MessageHandler.show(self, result, only_errors=True)
                self._all_records = []
                self._record_map = {}
                self.list_widget.set_records([])
                self._workspace_clear_active_record()
                self._sync_workspace_summary()
                return

            data = result.data or {}
            metadata = data.get("metadata", {}) or {}
            self._sync_filter_options(metadata)
            self._all_records = list(data.get("all_records", []) or data.get("records", []) or [])
            self._record_map = {str(row.get("recordKey") or "").strip(): row for row in self._all_records}
            self.summary_label.setText(str(data.get("summary_text") or "Toplam hareket: 0"))
            self.filter_info_label.setText(
                FINANCE_TRANSACTION_FILTER_INFO_TEMPLATE.format(
                    company=self.company_combo.currentText() or FINANCE_TRANSACTION_ALL_TEXT,
                    service=self.service_combo.currentText() or FINANCE_TRANSACTION_ALL_TEXT,
                    transaction_type=self.transaction_type_combo.currentText() or FINANCE_TRANSACTION_ALL_TEXT,
                )
            )
            if self._selected_record_key and self._selected_record_key not in self._record_map:
                self._selected_record_key = ""
            card_records = [FinanceTransactionWorkspaceRecord.from_row(record) for record in self._all_records]
            self.list_widget.set_records(card_records)
            active_record = next(
                (record for record in card_records if str(record.recordKey or "").strip() == self._selected_record_key),
                None,
            )
            if active_record is not None:
                self.list_widget.set_active_record(active_record)
            else:
                self.list_widget.clear_active_record()
            self._set_detail_record(self._record_map.get(self._selected_record_key))

        def _handle_finished() -> None:
            if self._reload_worker is worker:
                self._reload_worker = None
            worker.deleteLater()
            if seq == self._reload_seq:
                self._set_list_loading(False)
            if self._reload_pending:
                self._reload_pending = False
                QTimer.singleShot(0, self.reload_from_db)

        worker.result_ready.connect(_handle_result)
        worker.finished.connect(_handle_finished)
        worker.start()
