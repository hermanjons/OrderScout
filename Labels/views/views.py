from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QGroupBox, QPushButton, QMessageBox, QTextEdit, QDialogButtonBox
)
from PyQt6.QtCore import Qt

from Feedback.processors.pipeline import Result, map_error_to_message, MessageHandler

from Labels.constants.constants import LABEL_BRANDS, LABEL_MODELS_BY_BRAND
from Labels.processors.pipeline import create_order_label_from_orders  # 🔗 pipeline fonksiyonu
import json


class LabelPrintManagerWindow(QDialog):
    """
    Etiket yazdırma yönetim ekranı.
    - Marka seçimi
    - Model seçimi
    - Yazdır butonu:
        - Seçili siparişlerden etiket datasını hazırlayan pipeline'ı tetikler.

    Yazdır'a basılıp işlem başarılı olursa:
        - self.label_result içinde Result nesnesi
        - self.label_result.data içinde:
            - selected_order_numbers, orders, headers, order_data_list, order_item_list
            - brand_code, model_code
        tutulur ve dialog accept() ile kapanır.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.setWindowTitle("Etiket Yazdırma")
            self.setModal(True)
            self.setMinimumSize(400, 250)

            self.label_result: Result | None = None  # dışarıya veri taşımak için

            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(16, 16, 16, 16)
            main_layout.setSpacing(16)

            # ==============================
            # 📦 Şablon Seçimi
            # ==============================
            selection_box = QGroupBox("Şablon Seçimi")
            selection_layout = QVBoxLayout(selection_box)
            selection_layout.setContentsMargins(12, 12, 12, 12)
            selection_layout.setSpacing(12)

            # Marka
            row_brand = QHBoxLayout()
            row_brand.setSpacing(8)
            row_brand.addWidget(QLabel("Marka:"), stretch=0, alignment=Qt.AlignmentFlag.AlignVCenter)

            self.brand_combo = QComboBox()
            self.brand_combo.setEditable(False)
            row_brand.addWidget(self.brand_combo, stretch=1)
            selection_layout.addLayout(row_brand)

            # Model
            row_model = QHBoxLayout()
            row_model.setSpacing(8)
            row_model.addWidget(QLabel("Model:"), stretch=0, alignment=Qt.AlignmentFlag.AlignVCenter)

            self.model_combo = QComboBox()
            self.model_combo.setEditable(False)
            row_model.addWidget(self.model_combo, stretch=1)
            selection_layout.addLayout(row_model)

            main_layout.addWidget(selection_box)

            # ==============================
            # 🔘 Yazdır Butonu
            # ==============================
            buttons_layout = QHBoxLayout()
            buttons_layout.setContentsMargins(0, 8, 0, 0)
            buttons_layout.addStretch()

            self.print_button = QPushButton("Yazdır")
            self.print_button.setDefault(True)
            self.print_button.clicked.connect(self._on_print_clicked)

            buttons_layout.addWidget(self.print_button)
            main_layout.addLayout(buttons_layout)

            # ==============================
            # 🔄 Combobox doldurma
            # ==============================
            self._populate_brands()
            self.brand_combo.currentIndexChanged.connect(self._on_brand_changed)

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def _show_text_dump(self, title: str, text: str):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        lay = QVBoxLayout(dlg)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        lay.addWidget(view)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        dlg.resize(800, 600)
        dlg.exec()

    # --------------------------------------------------------
    # Marka / Model doldurma
    # --------------------------------------------------------
    def _populate_brands(self):
        try:
            self.brand_combo.clear()
            for brand in LABEL_BRANDS:
                self.brand_combo.addItem(brand["name"], userData=brand["code"])
            self._populate_models_for_current_brand()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def _on_brand_changed(self, _index: int):
        try:
            self._populate_models_for_current_brand()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def _populate_models_for_current_brand(self):
        try:
            brand_code = self.brand_combo.currentData()
            models = LABEL_MODELS_BY_BRAND.get(brand_code, [])
            self.model_combo.clear()
            for m in models:
                self.model_combo.addItem(m["name"], userData=m["code"])
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    # --------------------------------------------------------
    # Getter'lar
    # --------------------------------------------------------
    def get_selected_brand_code(self) -> str | None:
        return self.brand_combo.currentData()

    def get_selected_model_code(self) -> str | None:
        return self.model_combo.currentData()

    # --------------------------------------------------------
    # Yazdır butonu handler
    # --------------------------------------------------------
    def _on_print_clicked(self):
        """
        Akış:
        1) Marka & model kontrolü
        2) Parent içinden list_widget'i al
        3) create_order_label_from_orders(list_widget) çağır
        4) Başarılıysa Result'u zenginleştir, **label_payload**'ı metin olarak göster, dialog'u kapat
        """
        try:
            brand = self.get_selected_brand_code()
            model = self.get_selected_model_code()

            if not brand or not model:
                MessageHandler.show(
                    self,
                    Result.fail("Lütfen marka ve model seçiniz.", close_dialog=False),
                    only_errors=True
                )
                return

            parent = self.parent()
            if parent is None or not hasattr(parent, "list_widget"):
                MessageHandler.show(
                    self,
                    Result.fail(
                        "Liste kaynağı bulunamadı. Bu pencere OrdersManagerWindow üzerinden açılmalı.",
                        close_dialog=False
                    ),
                    only_errors=True
                )
                return

            list_widget = parent.list_widget

            # 🔗 Pipeline: seçili siparişlerden detayları çek
            res = create_order_label_from_orders(list_widget)

            if not res or not isinstance(res, Result):
                MessageHandler.show(
                    self,
                    Result.fail("Etiket verisi hazırlanırken beklenmeyen bir hata oluştu.",
                                close_dialog=False),
                    only_errors=True
                )
                return

            if not res.success:
                MessageHandler.show(self, res, only_errors=True)
                return

            # ✅ Başarılı: datayı al ve şablon bilgisini ekle
            data = res.data or {}
            data["brand_code"] = brand
            data["model_code"] = model
            res.data = data

            # 🧪 TEST: **label_payload**'ı düz metin (pretty JSON) olarak göster
            payload = data.get("label_payload", {})
            preview_dict = {
                "brand_code": brand,
                "model_code": model,
                "max_items_per_label": payload.get("max_items_per_label"),
                "total_labels": payload.get("total_labels"),
                "labels": payload.get("labels", []),  # istersen burada ilk N label'a kırpabilirsin
            }
            txt = json.dumps(preview_dict, ensure_ascii=False, indent=2)
            self._show_text_dump("Label Payload (TEST)", txt)

            # Son olarak Result'ı sakla (gerçek yazdırmada kullanacağız)
            self.label_result = res
            self.accept()

        except Exception as e:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(e), error=e, close_dialog=False),
                only_errors=True
            )
