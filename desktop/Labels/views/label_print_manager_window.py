# Labels/views/views.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from Core.threads.sync_worker import SyncWorker
from Core.views import SwitchSelectWidget
from Labels.constants import LABEL_BRANDS, LABEL_MODELS_BY_BRAND
from Orders.signals.signals import order_signals
from settings import ASSETS_DIR, resource_path


@dataclass
class LabelExportState:
    label_result: Result | None = None
    payload: dict | None = None
    sort_mode: str = "none"
    output_path: Path | None = None
    brand_code: str | None = None
    model_code: str | None = None
    template_path: Path | None = None


def _label_action(name: str):
    from Labels.views import actions

    return getattr(actions, name)


def apply_sort_to_payload(*args, **kwargs):
    return _label_action("apply_sort_to_payload")(*args, **kwargs)


def build_default_output_dir(*args, **kwargs):
    return _label_action("build_default_output_dir")(*args, **kwargs)


def build_label_payload(*args, **kwargs):
    return _label_action("build_label_payload")(*args, **kwargs)


def build_suggested_filename(*args, **kwargs):
    return _label_action("build_suggested_filename")(*args, **kwargs)


def ensure_any_selected_orders(*args, **kwargs):
    return _label_action("ensure_any_selected_orders")(*args, **kwargs)


def make_export_worker(*args, **kwargs):
    return _label_action("make_export_worker")(*args, **kwargs)


def mark_orders_extracted_from_label_result(*args, **kwargs):
    return _label_action("mark_orders_extracted_from_label_result")(*args, **kwargs)


def resolve_list_widget_from_parent(*args, **kwargs):
    return _label_action("resolve_list_widget_from_parent")(*args, **kwargs)


def resolve_template_path_from_cfg(*args, **kwargs):
    return _label_action("resolve_template_path_from_cfg")(*args, **kwargs)


class LabelPrintManagerWindow(QDialog):
    """Etiket yazdırma / Word çıktısı alma penceresi."""

    progress_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self._setup_window()
            self._init_state()
            self._build_ui()
            self._populate_brands()

            self.brand_combo.currentIndexChanged.connect(self._on_brand_changed)
            self.progress_changed.connect(self._on_progress_changed)
        except Exception as e:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(e), error=e, close_dialog=False),
                only_errors=True,
            )

    # -------------------------------------------------
    # Window / state
    # -------------------------------------------------
    def _setup_window(self):
        self.setWindowTitle("Etiket Yazdır / Word Çıkart")
        self.setModal(True)
        self.setMinimumSize(640, 420)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._print_icon = self._resolve_print_icon()
        if not self._print_icon.isNull():
            self.setWindowIcon(self._print_icon)

        self.setStyleSheet(
            """
            QDialog {
                background: #F3F4F6;
                color: #0F172A;
            }
            QFrame#Card {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
            QGroupBox#CardGroup {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                margin-top: 10px;
                padding-top: 8px;
                font-size: 13px;
                font-weight: 700;
                color: #0F172A;
            }
            QGroupBox#CardGroup::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
            QLabel#HeaderTitle {
                font-size: 18px;
                font-weight: 800;
                color: #0F172A;
            }
            QLabel#HeaderSubtitle {
                font-size: 12px;
                color: #475569;
            }
            QLabel#FieldKey {
                font-size: 12px;
                color: #64748B;
                font-weight: 600;
            }
            QLabel#StatusValue {
                font-size: 13px;
                color: #0F172A;
                font-weight: 700;
            }
            QComboBox {
                min-height: 34px;
                border: 1px solid #CBD5E1;
                border-radius: 10px;
                padding: 4px 10px;
                background: #FFFFFF;
                color: #0F172A;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QPushButton#PrimaryButton {
                background: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 10px;
                padding: 9px 16px;
                font-weight: 700;
                min-height: 18px;
            }
            QPushButton#PrimaryButton:hover {
                background: #1D4ED8;
            }
            QPushButton#PrimaryButton:disabled {
                background: #94A3B8;
                color: #E2E8F0;
            }
            QPushButton#SecondaryButton {
                background: #FFFFFF;
                color: #0F172A;
                border: 1px solid #CBD5E1;
                border-radius: 10px;
                padding: 9px 16px;
                font-weight: 700;
                min-height: 18px;
            }
            QPushButton#SecondaryButton:hover {
                background: #F8FAFC;
            }
            QProgressBar {
                min-height: 18px;
                border: 1px solid #D1D5DB;
                border-radius: 9px;
                background: #F8FAFC;
                text-align: center;
                font-size: 11px;
                color: #0F172A;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background: #22C55E;
            }
            """
        )

    def _resolve_print_icon(self) -> QIcon:
        candidate_paths = [
            Path(resource_path("images/print_extract.ico")),
            Path(ASSETS_DIR) / "print_extract.ico",
        ]
        for icon_path in candidate_paths:
            if icon_path.is_file():
                return QIcon(str(icon_path))
        return QIcon()

    def _init_state(self):
        self.state = LabelExportState()
        self._worker: SyncWorker | None = None
        self._is_exporting = False

    # -------------------------------------------------
    # UI
    # -------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        root.addWidget(self._build_header_card())
        root.addWidget(self._build_template_box())
        root.addWidget(self._build_status_card())
        root.addLayout(self._build_footer())

    def _build_header_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        icon_label = QLabel()
        icon_label.setFixedSize(26, 26)
        if not self._print_icon.isNull():
            icon_label.setPixmap(self._print_icon.pixmap(22, 22))
        row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title = QLabel("Etiket Yazdırma Merkezi")
        title.setObjectName("HeaderTitle")
        subtitle = QLabel("Şablon seç, sıralamayı belirle ve seçili siparişlerden Word etiketi üret.")
        subtitle.setObjectName("HeaderSubtitle")
        subtitle.setWordWrap(True)

        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        row.addLayout(text_col, 1)
        return card

    def _build_template_box(self) -> QGroupBox:
        box = QGroupBox("Etiket Şablonu")
        box.setObjectName("CardGroup")

        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addLayout(self._row("Marka", self._build_brand_combo()))
        layout.addLayout(self._row("Model", self._build_model_combo()))
        layout.addLayout(self._row("Sıralama", self._build_sort_combo()))
        return box

    def _build_status_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        col = QVBoxLayout(card)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(8)

        status_key = QLabel("Durum")
        status_key.setObjectName("FieldKey")

        self.lbl_status = QLabel("Hazır.")
        self.lbl_status.setObjectName("StatusValue")
        self.lbl_status.setWordWrap(True)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")

        col.addWidget(status_key)
        col.addWidget(self.lbl_status)
        col.addWidget(self.progress_bar)
        return card

    def _build_footer(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addStretch(1)

        self.close_button = QPushButton("Kapat")
        self.close_button.setObjectName("SecondaryButton")
        self.close_button.clicked.connect(self.reject)

        self.export_button = QPushButton("Word Çıkart")
        self.export_button.setObjectName("PrimaryButton")
        self.export_button.setDefault(True)
        self.export_button.setMinimumWidth(180)
        if not self._print_icon.isNull():
            self.export_button.setIcon(self._print_icon)
        self.export_button.clicked.connect(self._on_export_clicked)

        layout.addWidget(self.close_button)
        layout.addWidget(self.export_button)
        return layout

    # -------------------------------------------------
    # UI elements
    # -------------------------------------------------
    def _row(self, label: str, widget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        label_widget = QLabel(f"{label}:")
        label_widget.setObjectName("FieldKey")
        label_widget.setMinimumWidth(80)

        row.addWidget(label_widget, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(widget, 1)
        return row

    def _build_brand_combo(self) -> QComboBox:
        self.brand_combo = QComboBox()
        self.brand_combo.setEditable(False)
        return self.brand_combo

    def _build_model_combo(self) -> SwitchSelectWidget:
        self.model_combo = SwitchSelectWidget(
            self,
            empty_text="Etiket modelini seç",
            multi=False,
            search_enabled=True,
            include_all=False,
            default_all=False,
            allow_empty=False,
        )
        self.model_combo.setPlaceholderText("Etiket kodu ara (örn. 2610 veya TW-2610)")
        return self.model_combo

    def _build_sort_combo(self) -> QComboBox:
        self.sort_combo = QComboBox()
        self.sort_combo.setEditable(False)
        self.sort_combo.addItem("Orijinal sıra", userData="none")
        self.sort_combo.addItem("Ürün adına göre", userData="product")
        self.sort_combo.addItem("Adete göre", userData="quantity")
        self.sort_combo.addItem("Optimal (ürün + adet)", userData="optimal")
        return self.sort_combo

    # -------------------------------------------------
    # Populate
    # -------------------------------------------------
    def _populate_brands(self):
        self.brand_combo.clear()
        for brand in LABEL_BRANDS:
            self.brand_combo.addItem(brand["name"], userData=brand["code"])
        self._populate_models()

    def _on_brand_changed(self, _idx: int):
        self._populate_models()

    def _populate_models(self):
        self.model_combo.clear()
        brand_code = self.brand_combo.currentData()
        items = []
        for index, model in enumerate(LABEL_MODELS_BY_BRAND.get(brand_code, [])):
            reference = model.get("manufacturer_ref") or model["code"]
            description = model.get("desc") or model.get("name") or ""
            display = f"{reference} · {description}" if description else str(reference)
            items.append((display, model["code"], index == 0))
        self.model_combo.addItems(items)

    # -------------------------------------------------
    # Getters
    # -------------------------------------------------
    def get_selected_brand_code(self) -> str | None:
        return self.brand_combo.currentData()

    def get_selected_model_code(self) -> str | None:
        return self.model_combo.currentData()

    def get_sort_mode(self) -> str:
        return self.sort_combo.currentData() or "none"

    # -------------------------------------------------
    # Progress / state
    # -------------------------------------------------
    def _set_status(self, text: str):
        try:
            self.lbl_status.setText(str(text or ""))
        except Exception:
            pass

    def _set_exporting(self, exporting: bool):
        is_busy = bool(exporting)
        self._is_exporting = is_busy
        self.export_button.setEnabled(not is_busy)
        self.close_button.setEnabled(not is_busy)
        self.brand_combo.setEnabled(not is_busy)
        self.model_combo.setEnabled(not is_busy)
        self.sort_combo.setEnabled(not is_busy)
        self.export_button.setText("İşleniyor..." if is_busy else "Word Çıkart")

    def _on_progress_changed(self, pct: int):
        try:
            value = max(0, min(100, int(pct)))
            self.progress_bar.setValue(value)
            self._set_status(f"İlerleme: %{value}")
        except Exception:
            pass

    # -------------------------------------------------
    # Export flow
    # -------------------------------------------------
    def _on_export_clicked(self):
        try:
            if self._worker and self._worker.isRunning():
                return

            brand = self.get_selected_brand_code()
            model = self.get_selected_model_code()
            if not brand or not model:
                self._fail("Lütfen marka ve model seçiniz.")
                return

            lw_res = resolve_list_widget_from_parent(self)
            if not lw_res.success:
                self._fail(lw_res)
                return
            list_widget = lw_res.data["list_widget"]

            sel_res = ensure_any_selected_orders(list_widget)
            if not sel_res.success:
                self._fail(sel_res)
                return

            file_path = self._ask_output_path(model)
            if not file_path:
                self._set_status("İşlem iptal edildi.")
                self.progress_bar.setValue(0)
                return

            self._start_progress()
            self._set_status("Payload hazırlanıyor...")

            pres = build_label_payload(
                list_widget=list_widget,
                brand_code=brand,
                model_code=model,
            )
            if not pres.success:
                self._fail(pres)
                return

            label_result = pres.data["label_result"]
            payload = pres.data["payload"]

            sres = apply_sort_to_payload(
                payload=payload,
                sort_mode=self.get_sort_mode(),
            )
            payload = sres.data["payload"] if sres.success else payload

            tres = resolve_template_path_from_cfg(brand_code=brand, model_code=model)
            if not tres.success:
                self._fail(tres)
                return
            self._set_status("Export başlatılıyor...")

            self._start_worker(
                payload=payload,
                brand=brand,
                model=model,
                output_path=Path(file_path),
                template_path=tres.data["template_path"],
                label_result=label_result,
            )
        except Exception as e:
            self._fail(Result.fail(map_error_to_message(e), error=e, close_dialog=False))

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------
    def _ask_output_path(self, model_code: str) -> str | None:
        dres = build_default_output_dir()
        fres = build_suggested_filename(model_code=model_code)
        if not dres.success or not fres.success:
            return None

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Word etiket dosyasını kaydet",
            str(dres.data["dir"] / fres.data["filename"]),
            "Word Dosyası (*.docx)",
        )
        return path or None

    def _start_progress(self):
        self._set_exporting(True)
        self.progress_bar.setValue(0)
        self._set_status("Export başladı...")

    def _start_worker(self, *, payload, brand, model, output_path, template_path, label_result):
        self.state.label_result = label_result
        self.state.payload = payload
        self.state.output_path = output_path

        def progress_cb(p: int):
            self.progress_changed.emit(p)

        wres = make_export_worker(
            worker_cls=SyncWorker,
            payload=payload,
            brand_code=brand,
            model_code=model,
            output_path=output_path,
            template_path=template_path,
            progress_cb=progress_cb,
        )
        if not wres.success:
            self._fail(wres)
            return

        self._worker = wres.data["worker"]
        self._worker.result_ready.connect(self._on_worker_result)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _fail(self, res):
        MessageHandler.show(self, res, only_errors=True)
        self._set_exporting(False)
        if isinstance(res, Result):
            self._set_status(f"Hata: {res.message}")
        elif isinstance(res, str):
            self._set_status(f"Hata: {res}")
        else:
            self._set_status("Hata oluştu.")

    # -------------------------------------------------
    # Worker callbacks
    # -------------------------------------------------
    def _on_worker_result(self, result: Result):
        if not result.success:
            self._fail(result)
            return

        self.progress_changed.emit(100)
        self._set_status("Export tamamlandı.")

        upd = mark_orders_extracted_from_label_result(self.state.label_result)
        if not upd.success:
            print("[OrderHeader update warning]", upd.message)

        MessageHandler.show(
            self,
            Result.ok(
                f"Word etiket dosyası oluşturuldu:\n{self.state.output_path}",
                close_dialog=False,
            ),
            only_errors=False,
        )

        order_signals.orders_changed.emit()
        self.accept()

    def _on_worker_finished(self):
        self._worker = None
        self._set_exporting(False)
