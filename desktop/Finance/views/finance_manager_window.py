from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import QDate, Qt, QSignalBlocker, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
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
    FINANCE_INVOICE_ALL_TEXT,
    FINANCE_INVOICE_COMPANY_LABEL,
    FINANCE_INVOICE_COMPANY_SUBTITLE_TEMPLATE,
    FINANCE_INVOICE_DATE_RANGE_LABEL,
    FINANCE_INVOICE_DETAIL_HINT,
    FINANCE_INVOICE_DETAIL_TITLE,
    FINANCE_INVOICE_EMPTY_TEXT,
    FINANCE_INVOICE_FILTER_INFO_TEMPLATE,
    FINANCE_INVOICE_FILTERS_SUBTITLE,
    FINANCE_INVOICE_ORDER_COUNT_LABEL,
    FINANCE_INVOICE_RECORDS_SUBTITLE,
    FINANCE_INVOICE_RECORDS_SUMMARY_TEMPLATE,
    FINANCE_INVOICE_RECORDS_TITLE,
    FINANCE_INVOICE_RESET_FILTERS_TEXT,
    FINANCE_INVOICE_SEARCH_PLACEHOLDER,
    FINANCE_INVOICE_SELLER_ACCOUNT_LABEL,
    FINANCE_INVOICE_WINDOW_TITLE,
)
from settings import ASSETS_DIR


def _finance_default_date_range():
    try:
        from Finance.constants.trendyol.constants import TRENDYOL_FINANCE_DEFAULT_FETCH_DAYS, TZ_GMT3

        today = datetime.now(TZ_GMT3).date()
        start = today - timedelta(days=max(1, int(TRENDYOL_FINANCE_DEFAULT_FETCH_DAYS)) - 1)
        return start, today
    except Exception:
        today = datetime.now(timezone(timedelta(hours=3))).date()
        return today - timedelta(days=13), today


def _load_finance_cargo_invoices_from_db(**kwargs):
    from Finance.views.actions import load_finance_invoice_documents_from_db

    invoice_type = kwargs.pop("package_type", "")
    return load_finance_invoice_documents_from_db(invoice_type=invoice_type, **kwargs)


def _save_finance_invoice_document(payload: dict):
    from Finance.views.actions import save_finance_invoice_document

    return save_finance_invoice_document(payload)


class FinanceInvoiceCard(QFrame):
    selectedChanged = pyqtSignal(str)

    def __init__(self, record: dict, *, icon_path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.record = dict(record or {})
        self.record_key = str(self.record.get("recordKey") or "")
        self.setObjectName("FinanceListCard")
        self.setProperty("selected", False)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        icon_label = QLabel(self)
        icon_label.setFixedSize(56, 56)
        pixmap = QPixmap(icon_path)
        if not pixmap.isNull():
            icon_label.setPixmap(
                pixmap.scaled(
                    56,
                    56,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        root.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(6)

        title = QLabel(f"Fatura: {self.record.get('invoiceNumber') or self.record.get('invoiceSerialNumber', '-')}", objectName="InvoiceTitle")
        title.setWordWrap(True)
        text_col.addWidget(title)

        company = QLabel(
            FINANCE_INVOICE_COMPANY_SUBTITLE_TEMPLATE.format(company=self.record.get("companyName", "-"))
            + f" | Tarih: {self.record.get('transactionDateText', '-')}",
            objectName="InvoiceMeta",
        )
        company.setWordWrap(True)
        text_col.addWidget(company)

        totals = QLabel(
            f"Tür: {self.record.get('invoiceTypeText', '-')} | "
            f"Tutar: {self.record.get('totalAmountText', '0.00')} {self.record.get('currency') or 'TRY'}",
            objectName="InvoiceMetaStrong",
        )
        totals.setWordWrap(True)
        text_col.addWidget(totals)

        extras = QLabel(
            f"Dosya: {self.record.get('fileName', '-')} | Referans: {self.record.get('referenceText', '-')}",
            objectName="InvoiceMeta",
        )
        extras.setWordWrap(True)
        text_col.addWidget(extras)

        root.addLayout(text_col, 1)

        self.select_button = QPushButton("SEÇ", self)
        self.select_button.setObjectName("SelectButton")
        self.select_button.clicked.connect(self._emit_selected)
        root.addWidget(self.select_button, alignment=Qt.AlignmentFlag.AlignVCenter)

    def _emit_selected(self) -> None:
        self.selectedChanged.emit(self.record_key)

    def mousePressEvent(self, event) -> None:
        self._emit_selected()
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        self.select_button.setProperty("selected", bool(selected))
        self.select_button.setText("SEÇİLİ" if selected else "SEÇ")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        self.select_button.style().unpolish(self.select_button)
        self.select_button.style().polish(self.select_button)
        self.select_button.update()


@dataclass
class FinanceInvoiceWorkspaceRecord(RecordWorkspaceCardRecord):
    @classmethod
    def from_row(cls, record: dict) -> "FinanceInvoiceWorkspaceRecord":
        payload = dict(record or {})
        return cls(
            orderNumber=str(payload.get("recordKey") or ""),
            title=f"Fatura: {payload.get('invoiceNumber') or payload.get('invoiceSerialNumber') or '-'}",
            subtitle=(
                FINANCE_INVOICE_COMPANY_SUBTITLE_TEMPLATE.format(company=payload.get("companyName") or "-")
                + " | "
                f"Tarih: {payload.get('transactionDateText') or '-'}"
            ),
            extra=(
                f"Tür: {payload.get('invoiceTypeText') or '-'} | "
                f"Tutar: {payload.get('totalAmountText', '0.00')} {payload.get('currency') or 'TRY'} | "
                f"Dosya: {payload.get('fileName') or '-'} | "
                f"Referans: {payload.get('referenceText') or '-'}"
            ),
            logo_path=str(ASSETS_DIR / "finance-invoices-icon.png"),
            payload=payload,
        )


class FinanceInvoiceListWidget(RecordWorkspaceListWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, empty_placeholder_text=FINANCE_INVOICE_EMPTY_TEXT)


class FinanceInvoicesWorkspaceAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, window: "FinanceManagerWindow") -> None:
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
        self.window._prepare_new_invoice_document()

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
        return FINANCE_INVOICE_DETAIL_HINT

    def bulk_guidance_message(self) -> str:
        return ""


class FinanceManagerWindow(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("FinanceRoot")
        self.setStyleSheet(FINANCE_STYLE)
        self.setWindowTitle(FINANCE_INVOICE_WINDOW_TITLE)
        self.setWindowIcon(QIcon(os.path.join(ASSETS_DIR, "finance-invoices-icon.png")))
        self.setGeometry(220, 120, 1500, 860)

        self._suspend_reload = False
        self._has_loaded_once = False
        self._all_records: list[dict] = []
        self._record_map: dict[str, dict] = {}
        self._selected_record_key: str = ""
        self._mode = "edit"
        self._left_stick_size = 460

        self._search_timer = QTimer(self)
        self._search_timer.setInterval(250)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.reload_from_db)
        self._initial_reload_timer = QTimer(self)
        self._initial_reload_timer.setInterval(0)
        self._initial_reload_timer.setSingleShot(True)
        self._initial_reload_timer.timeout.connect(self.reload_from_db)
        self._reload_worker: SyncWorker | None = None
        self._reload_pending = False
        self._reload_seq = 0

        self._workspace = RecordWorkspaceScaffold(
            self,
            empty_placeholder_text=FINANCE_INVOICE_EMPTY_TEXT,
            left_title=FINANCE_INVOICE_DETAIL_TITLE,
            left_subtitle=FINANCE_INVOICE_DETAIL_HINT,
            filters_title="Filtreler",
            filters_subtitle=FINANCE_INVOICE_FILTERS_SUBTITLE,
            records_title=FINANCE_INVOICE_RECORDS_TITLE,
            records_subtitle=FINANCE_INVOICE_RECORDS_SUBTITLE,
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": "Fatura sureti ekle",
                    "icon_path": str(ASSETS_DIR / "yeni-kayit.png"),
                    "shape": "circular",
                    "icon_scale": 1.18,
                },
                {
                    "panel_id": "detail",
                    "text": "",
                    "tooltip": "Fatura detay paneli",
                    "icon_path": str(ASSETS_DIR / "duzenleme-icon.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
            ),
            shell_kwargs={
                "sidebar_width": 92,
                "left_stick_size": self._left_stick_size,
                "left_collapse_trigger": 420,
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
        self._panel_sidebar = self._workspace.sidebar
        self.left_panel_title = self._workspace.left_card.title_label
        self.left_panel_hint = self._workspace.left_card.subtitle_label

        self.editor_stack = QStackedWidget(self)
        self.invoice_form: QWidget | None = None

        self.detail_card = QWidget(self)
        detail_layout = QVBoxLayout(self.detail_card)
        detail_layout.setContentsMargins(14, 12, 14, 12)
        detail_layout.setSpacing(10)

        self.detail_empty_label = QLabel(FINANCE_INVOICE_DETAIL_HINT, objectName="Muted")
        self.detail_empty_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_empty_label)

        info_grid = QGridLayout()
        info_grid.setContentsMargins(0, 0, 0, 0)
        info_grid.setHorizontalSpacing(10)
        info_grid.setVerticalSpacing(8)
        self._detail_fields: dict[str, QLabel] = {}
        detail_rows = [
            ("invoiceNumber", "Fatura No"),
            ("invoiceTypeText", "Fatura Türü"),
            ("companyName", FINANCE_INVOICE_COMPANY_LABEL),
            ("transactionDateText", "Tarih"),
            ("totalAmountText", "Toplam Tutar"),
            ("currency", "Para Birimi"),
            ("fileType", "Dosya Türü"),
            ("fileName", "Dosya"),
            ("referenceText", "Referans"),
        ]
        for idx, (field_key, title) in enumerate(detail_rows):
            card = QFrame(self.detail_card)
            card.setObjectName("DetailMetricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(2)
            card_layout.addWidget(QLabel(title, objectName="DetailCaption"))
            value_label = QLabel("-", objectName="DetailValue")
            value_label.setWordWrap(True)
            card_layout.addWidget(value_label)
            self._detail_fields[field_key] = value_label
            info_grid.addWidget(card, idx // 2, idx % 2)
        detail_layout.addLayout(info_grid)

        detail_layout.addWidget(QLabel("Belge Bilgileri", objectName="SectionTitle"))
        self.detail_table = self._make_table(["Alan", "Değer"], min_height=320)
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
        top_row.setSpacing(10)
        top_row.addStretch(1)
        self.btn_reset = QPushButton(FINANCE_INVOICE_RESET_FILTERS_TEXT)
        self.btn_reset.setObjectName("SoftDanger")
        self.btn_reset.clicked.connect(self._reset_filters)
        top_row.addWidget(self.btn_reset)
        filter_layout.addLayout(top_row)

        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("Input")
        self.search_input.setPlaceholderText(FINANCE_INVOICE_SEARCH_PLACEHOLDER)
        self.search_input.textChanged.connect(self._schedule_reload)
        filter_layout.addWidget(self.search_input)

        filter_grid = QGridLayout()
        filter_grid.setContentsMargins(0, 0, 0, 0)
        filter_grid.setHorizontalSpacing(10)
        filter_grid.setVerticalSpacing(8)

        self.company_combo = QComboBox(self)
        self.company_combo.setObjectName("Combo")
        self.company_combo.currentIndexChanged.connect(self.reload_from_db)

        self.package_type_combo = QComboBox(self)
        self.package_type_combo.setObjectName("Combo")
        self.package_type_combo.currentIndexChanged.connect(self.reload_from_db)

        self.date_range = DateSelector(range_enabled=True)
        self.date_range.rangeChanged.connect(lambda *_: self.reload_from_db())
        start_default, end_default = _finance_default_date_range()
        self.date_range.setRange(
            QDate(start_default.year, start_default.month, start_default.day),
            QDate(end_default.year, end_default.month, end_default.day),
        )

        filter_grid.addWidget(QLabel(FINANCE_INVOICE_COMPANY_LABEL, objectName="Muted"), 0, 0)
        filter_grid.addWidget(self.company_combo, 1, 0)
        filter_grid.addWidget(QLabel("Fatura Türü", objectName="Muted"), 0, 1)
        filter_grid.addWidget(self.package_type_combo, 1, 1)
        filter_grid.addWidget(QLabel(FINANCE_INVOICE_DATE_RANGE_LABEL, objectName="Muted"), 0, 2)
        filter_grid.addWidget(self.date_range, 1, 2)
        filter_layout.addLayout(filter_grid)

        self.filter_info_label = QLabel(
            FINANCE_INVOICE_FILTER_INFO_TEMPLATE.format(
                company=FINANCE_INVOICE_ALL_TEXT,
                package=FINANCE_INVOICE_ALL_TEXT,
            ),
            objectName="StatusInfo",
        )
        self.filter_info_label.setWordWrap(True)
        filter_layout.addWidget(self.filter_info_label)

        self.summary_label = QLabel("Toplam fatura: 0", objectName="StatusInfo")
        self.summary_label.setWordWrap(True)
        filter_layout.addWidget(self.summary_label)
        self._workspace.set_filters_widget(filters_host)

        self.list_widget = FinanceInvoiceListWidget(self._workspace.records_card)
        self.list_widget.page_changed.connect(lambda *_args: self._sync_workspace_summary())
        self._workspace.set_list_widget(self.list_widget)
        self._workspace.footer_bar.select_toggle.hide()
        self._workspace_shell.close_left_panel()
        self._workspace.set_records_summary_text(
            FINANCE_INVOICE_RECORDS_SUMMARY_TEMPLATE.format(shown=0, total=0)
        )

        self._workspace_adapter = FinanceInvoicesWorkspaceAdapter(self)
        self._workspace_controller = self._workspace.create_behavior_controller(adapter=self._workspace_adapter)

        self._set_detail_record(None)

    def _build_invoice_form(self) -> QWidget:
        from PyQt6.QtWidgets import QPlainTextEdit

        from Core.views import FileBadgePicker
        from Finance.constants.domain_constants import FINANCE_CURRENCY_OPTIONS

        form = QWidget(self)
        layout = QVBoxLayout(form)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Fatura Sureti Ekle", objectName="SectionTitle"))
        hint = QLabel("Bu alana yalnızca resmi karşılığı olan fatura dosyalarını ekle.", objectName="Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.invoice_number_input = QLineEdit(self)
        self.invoice_number_input.setObjectName("Input")
        self.invoice_number_input.setPlaceholderText("Fatura no / seri")

        self.invoice_type_input = QComboBox(self)
        self.invoice_type_input.setObjectName("Combo")
        for label, value in (
            ("Gider Faturası", "expense"),
            ("Alış Faturası", "purchase"),
            ("Satış Faturası", "sales"),
            ("Kargo Faturası", "cargo"),
            ("Komisyon Faturası", "commission"),
            ("Diğer Fatura", "other"),
        ):
            self.invoice_type_input.addItem(label, value)

        self.invoice_date_input = DateSelector()
        self.invoice_date_input.setDate(QDate.currentDate())

        self.invoice_amount_input = QLineEdit(self)
        self.invoice_amount_input.setObjectName("Input")
        self.invoice_amount_input.setPlaceholderText("Örn. 1250,00")

        self.invoice_currency_input = QComboBox(self)
        self.invoice_currency_input.setObjectName("Combo")
        for code in FINANCE_CURRENCY_OPTIONS:
            self.invoice_currency_input.addItem(str(code), str(code))
        try_idx = self.invoice_currency_input.findText("TRY")
        self.invoice_currency_input.setCurrentIndex(try_idx if try_idx >= 0 else 0)

        self.invoice_counterparty_input = QLineEdit(self)
        self.invoice_counterparty_input.setObjectName("Input")
        self.invoice_counterparty_input.setPlaceholderText("Fatura tarafı")

        self.invoice_reference_input = QLineEdit(self)
        self.invoice_reference_input.setObjectName("Input")
        self.invoice_reference_input.setPlaceholderText("Pazaryeri, ödeme veya muhasebe referansı")

        fields = [
            ("Fatura No", self.invoice_number_input),
            ("Fatura Türü", self.invoice_type_input),
            ("Fatura Tarihi", self.invoice_date_input),
            ("Toplam Tutar", self.invoice_amount_input),
            ("Para Birimi", self.invoice_currency_input),
            ("Firma / Kişi", self.invoice_counterparty_input),
            ("Referans", self.invoice_reference_input),
        ]
        for idx, (label, widget) in enumerate(fields):
            grid.addWidget(QLabel(label, objectName="Muted"), idx, 0)
            grid.addWidget(widget, idx, 1)
        layout.addLayout(grid)

        self.invoice_file_picker = FileBadgePicker(
            self,
            button_text="Fatura Dosyası Seç",
            dialog_title="Fatura sureti seç",
            dialog_filter="Fatura Belgeleri (*.pdf *.png *.jpg *.jpeg *.webp *.xml *.html);;Tüm Dosyalar (*)",
            allowed_extensions=[".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xml", ".html"],
            allow_multiple=False,
            show_clear_button=True,
        )
        layout.addWidget(self.invoice_file_picker)

        layout.addWidget(QLabel("Not", objectName="Muted"))
        self.invoice_note_input = QPlainTextEdit(self)
        self.invoice_note_input.setObjectName("Input")
        self.invoice_note_input.setMaximumHeight(78)
        layout.addWidget(self.invoice_note_input)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.btn_invoice_clear = QPushButton("Temizle")
        self.btn_invoice_clear.setObjectName("SoftDanger")
        self.btn_invoice_clear.clicked.connect(self._clear_invoice_form)
        self.btn_invoice_save = QPushButton("Kaydet")
        self.btn_invoice_save.setObjectName("Primary")
        self.btn_invoice_save.clicked.connect(self._save_invoice_form)
        button_row.addWidget(self.btn_invoice_clear)
        button_row.addWidget(self.btn_invoice_save)
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
        for idx in range(len(headers)):
            resize_mode = QHeaderView.ResizeMode.ResizeToContents if idx == 0 else QHeaderView.ResizeMode.Stretch
            header.setSectionResizeMode(idx, resize_mode)
        return table

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._has_loaded_once:
            self._has_loaded_once = True
            self._set_list_loading(True)
            self._initial_reload_timer.start()

    def _set_list_loading(self, busy: bool, message: str = "Fatura suretleri yükleniyor...") -> None:
        self._workspace.set_list_loading(bool(busy), message=message)
        self._workspace.sync_list_loading_geometry()

    def _is_detail_panel_open(self) -> bool:
        return self._workspace_shell.is_left_panel_open()

    def _sync_workspace_summary(self) -> None:
        total = len(self._all_records)
        shown = self.list_widget.shown_count()
        self._workspace.set_records_summary_text(
            FINANCE_INVOICE_RECORDS_SUMMARY_TEMPLATE.format(shown=shown, total=total)
        )
        self._workspace.set_filters_footer_text(self.summary_label.text())

    def _sync_workspace_state(self) -> None:
        if self._mode == "new":
            self._workspace.set_left_title("Fatura Sureti Ekle")
            self._workspace.set_left_subtitle("Resmi fatura dosyası kaydı")
            self.list_widget.set_active_spin_allowed(False)
            self._sync_workspace_summary()
            return
        record = self._record_map.get(self._selected_record_key, {})
        if self._selected_record_key:
            self._workspace.set_left_title(f"Fatura: {record.get('invoiceNumber') or record.get('invoiceSerialNumber') or '-'}")
            self._workspace.set_left_subtitle(
                FINANCE_INVOICE_COMPANY_SUBTITLE_TEMPLATE.format(company=record.get("companyName") or "-")
            )
        else:
            self._workspace.set_left_title(FINANCE_INVOICE_DETAIL_TITLE)
            self._workspace.set_left_subtitle(FINANCE_INVOICE_DETAIL_HINT)
        self.list_widget.set_active_spin_allowed(self._is_detail_panel_open() and bool(self._selected_record_key))
        self._sync_workspace_summary()

    def _sync_sidebar_state_from_splitter(self) -> None:
        controller = getattr(self, "_workspace_controller", None)
        if controller is not None:
            controller.sync_state()

    def _open_detail_panel(self) -> None:
        self._workspace_shell.open_left_panel(left_width=self._left_stick_size, min_left=420, min_right=320)

    def _close_detail_panel(self) -> None:
        self._workspace_shell.close_left_panel()

    def _prepare_new_invoice_document(self) -> None:
        self._mode = "new"
        self._selected_record_key = ""
        if hasattr(self, "list_widget"):
            self.list_widget.clear_active_record()
        if self.invoice_form is None:
            self.invoice_form = self._build_invoice_form()
            self.editor_stack.insertWidget(0, self.invoice_form)
        self.editor_stack.setCurrentWidget(self.invoice_form)
        self._workspace.set_left_title("Fatura Sureti Ekle")
        self._workspace.set_left_subtitle("Resmi fatura dosyası kaydı")
        self._clear_invoice_form(reset_date=False)

    def _clear_invoice_form(self, *, reset_date: bool = True) -> None:
        if self.invoice_form is None:
            return
        self.invoice_number_input.clear()
        self.invoice_type_input.setCurrentIndex(0)
        if reset_date:
            self.invoice_date_input.setDate(QDate.currentDate())
        self.invoice_amount_input.clear()
        idx = self.invoice_currency_input.findText("TRY")
        self.invoice_currency_input.setCurrentIndex(idx if idx >= 0 else 0)
        self.invoice_counterparty_input.clear()
        self.invoice_reference_input.clear()
        self.invoice_file_picker.clearFiles()
        self.invoice_note_input.clear()

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
        return value if value >= 0 else None

    def _save_invoice_form(self) -> None:
        files = self.invoice_file_picker.files()
        if not files:
            MessageHandler.show(self, Result.fail("Resmi fatura sureti için dosya seçilmelidir.", close_dialog=False), only_errors=True)
            return
        amount = self._parse_amount_text(self.invoice_amount_input.text())
        payload = {
            "invoiceNumber": self.invoice_number_input.text().strip(),
            "invoiceType": self.invoice_type_input.currentData(),
            "invoiceDate": self.invoice_date_input.date().toPyDate(),
            "totalAmount": amount,
            "currency": self.invoice_currency_input.currentText(),
            "counterparty": self.invoice_counterparty_input.text().strip() or None,
            "sourceReference": self.invoice_reference_input.text().strip() or None,
            "filePath": files[0],
            "note": self.invoice_note_input.toPlainText().strip() or None,
        }
        result = _save_finance_invoice_document(payload)
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        self._clear_invoice_form()
        self._mode = "edit"
        self.editor_stack.setCurrentWidget(self.detail_card)
        self.reload_from_db()
        MessageHandler.show(self, result, only_errors=False)

    def _schedule_reload(self) -> None:
        if self._suspend_reload:
            return
        self._search_timer.start()

    def _fill_combo(self, combo: QComboBox, items: list[str], current_value: str = "") -> None:
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItem(FINANCE_INVOICE_ALL_TEXT, "")
            for item in items:
                if isinstance(item, tuple):
                    label, value = item[0], item[1]
                else:
                    label, value = item, item
                text = str(label or "").strip()
                if text:
                    combo.addItem(text, str(value or "").strip())
            idx = combo.findData(current_value)
            combo.setCurrentIndex(idx if idx >= 0 else 0)

    @staticmethod
    def _invoice_type_label(value: object) -> str:
        labels = {
            "expense": "Gider Faturası",
            "purchase": "Alış Faturası",
            "sales": "Satış Faturası",
            "cargo": "Kargo Faturası",
            "commission": "Komisyon Faturası",
            "other": "Diğer Fatura",
        }
        key = str(value or "").strip().casefold()
        return labels.get(key, str(value or "").strip() or "-")

    def _reset_filters(self) -> None:
        self._suspend_reload = True
        try:
            self.search_input.clear()
            self.company_combo.setCurrentIndex(0)
            self.package_type_combo.setCurrentIndex(0)
            start_default, end_default = _finance_default_date_range()
            self.date_range.setRange(
                QDate(start_default.year, start_default.month, start_default.day),
                QDate(end_default.year, end_default.month, end_default.day),
            )
        finally:
            self._suspend_reload = False
        self.reload_from_db()

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
            value = record.get(key)
            if key == "totalAmountText":
                value = f"{record.get('totalAmountText', '0.00')} {record.get('currency') or 'TRY'}"
            label.setText(str(value or "-"))

        rows = [
            ("Fatura No", record.get("invoiceNumber") or record.get("invoiceSerialNumber")),
            ("Fatura Türü", record.get("invoiceTypeText")),
            ("Firma / Kişi", record.get("counterparty") or record.get("companyName")),
            ("Fatura Tarihi", record.get("transactionDateText")),
            ("Vade Tarihi", record.get("dueDateText")),
            ("Toplam Tutar", f"{record.get('totalAmountText', '0.00')} {record.get('currency') or 'TRY'}"),
            ("KDV Tutarı", f"{record.get('vatAmountText', '0.00')} {record.get('currency') or 'TRY'}"),
            ("Dosya", record.get("filePath")),
            ("Dosya Türü", record.get("fileType")),
            ("Resmi Durum", record.get("officialStatus")),
            ("Referans", record.get("referenceText")),
            ("Not", record.get("note")),
        ]
        table = self.detail_table
        with optimized_table_updates(table, len(rows)):
            for row_idx, (label, value) in enumerate(rows):
                table.setItem(row_idx, 0, QTableWidgetItem(str(label)))
                table.setItem(row_idx, 1, QTableWidgetItem("-" if value in (None, "") else str(value)))
        self._sync_workspace_state()

    def _workspace_clear_active_record(self) -> None:
        self._selected_record_key = ""
        self.list_widget.clear_active_record()
        self._set_detail_record(None)

    def _workspace_activate_record(self, record: FinanceInvoiceWorkspaceRecord) -> None:
        payload = dict(getattr(record, "payload", {}) or {})
        record_key = str(payload.get("recordKey") or record.recordKey or "").strip()
        if not record_key:
            return
        self.list_widget.set_active_record(record)
        self._selected_record_key = record_key
        self._set_detail_record(self._record_map.get(record_key))

    def _sync_filter_options(self, metadata: dict) -> None:
        current_company = str(self.company_combo.currentData() or "").strip()
        current_package = str(self.package_type_combo.currentData() or "").strip()
        self._fill_combo(self.company_combo, list(metadata.get("company_names", []) or []), current_company)
        invoice_types = list(metadata.get("invoice_types", []) or metadata.get("package_types", []) or [])
        type_labels = [(self._invoice_type_label(item), item) for item in invoice_types]
        self._fill_combo(self.package_type_combo, type_labels, current_package)

    def _sync_active_list_record(self, records: list[FinanceInvoiceWorkspaceRecord]) -> None:
        active_record = next(
            (record for record in records if str(record.recordKey or "").strip() == self._selected_record_key),
            None,
        )
        if active_record is not None:
            self.list_widget.set_active_record(active_record)
        else:
            self.list_widget.clear_active_record()

    def reload_from_db(self, *_args, page: int | None = None) -> None:
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
            _load_finance_cargo_invoices_from_db,
            search_text=self.search_input.text().strip(),
            company_name=str(self.company_combo.currentData() or "").strip(),
            package_type=str(self.package_type_combo.currentData() or "").strip(),
            date_from=self.date_range.dateFrom().toPyDate(),
            date_to=self.date_range.dateTo().toPyDate(),
            page=max(1, int(page or 1)),
            page_size=max(20, int(getattr(self.list_widget, "page_size", 20) or 20)),
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
            self.summary_label.setText(str(data.get("summary_text") or "Toplam fatura: 0"))
            self.filter_info_label.setText(
                FINANCE_INVOICE_FILTER_INFO_TEMPLATE.format(
                    company=self.company_combo.currentText() or FINANCE_INVOICE_ALL_TEXT,
                    package=self.package_type_combo.currentText() or FINANCE_INVOICE_ALL_TEXT,
                )
            )

            if self._selected_record_key and self._selected_record_key not in self._record_map:
                self._selected_record_key = ""

            card_records = [FinanceInvoiceWorkspaceRecord.from_row(record) for record in self._all_records]
            self.list_widget.set_records(card_records)
            self._sync_active_list_record(card_records)
            self._set_detail_record(self._record_map.get(self._selected_record_key))
            self._sync_sidebar_state_from_splitter()

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
