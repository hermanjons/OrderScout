from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QGroupBox, QPushButton, QTextEdit, QDialogButtonBox
)
from PyQt6.QtCore import Qt

from Feedback.processors.pipeline import Result, map_error_to_message, MessageHandler

from Labels.constants.constants import LABEL_BRANDS, LABEL_MODELS_BY_BRAND
from Labels.processors.pipeline import (
    create_order_label_from_orders,
    export_labels_to_word,
    sort_label_payload,
)

import json
from pathlib import Path
from datetime import datetime


class LabelPrintManagerWindow(QDialog):
    """
    Etiket yazdırma yönetim ekranı.
    - Marka seçimi
    - Model seçimi
    - Sıralama seçimi
    - Yazdır butonu:
        - Seçili siparişlerden etiket datasını hazırlayan pipeline'ı tetikler.

    Yazdır'a basılıp işlem başarılı olursa:
        - self.label_result içinde Result nesnesi
        - self.label_result.data içinde:
            - label_payload (sıralama uygulanmış haliyle)
            - diğer sipariş verileri
        tutulur ve dialog accept() ile kapanır.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.setWindowTitle("Etiket Yazdırma")
            self.setModal(True)
            self.setMinimumSize(450, 280)

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

            # Sıralama tipi
            row_sort = QHBoxLayout()
            row_sort.setSpacing(8)
            row_sort.addWidget(QLabel("Sıralama:"), stretch=0, alignment=Qt.AlignmentFlag.AlignVCenter)

            self.sort_combo = QComboBox()
            self.sort_combo.setEditable(False)
            # userData ile sıralama modlarını tutuyoruz
            self.sort_combo.addItem("Orijinal sıra", userData="none")
            self.sort_combo.addItem("Ürün adına göre", userData="product")
            self.sort_combo.addItem("Adete göre", userData="quantity")
            self.sort_combo.addItem("Optimal (ürün + adet)", userData="optimal")

            row_sort.addWidget(self.sort_combo, stretch=1)
            selection_layout.addLayout(row_sort)

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

    # --------------------------------------------------------
    # Yardımcı: Metin dump gösterici (debug)
    # --------------------------------------------------------
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

    def get_sort_mode(self) -> str:
        """
        Kullanıcının seçtiği sıralama modunu döner.
        none / product / quantity / optimal
        """
        data = self.sort_combo.currentData()
        return data or "none"

    # --------------------------------------------------------
    # Yazdır butonu handler
    # --------------------------------------------------------
    def _on_print_clicked(self):
        """
        Akış:
        1) Marka & model kontrolü
        2) Parent içinden list_widget'i al
        3) create_order_label_from_orders(list_widget) çağır
        4) Kullanıcının seçtiği sıralama moduna göre label_payload'ı sırala
        5) Başarılıysa payload'tan Word çıktısı üret
        6) İsteğe bağlı: label_payload'ın özetini text olarak göster
        """
        try:
            brand = self.get_selected_brand_code()
            model = self.get_selected_model_code()
            sort_mode = self.get_sort_mode()

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

            # 🔗 Pipeline: seçili siparişlerden label payload üret
            res = create_order_label_from_orders(
                list_widget,
                brand_code=brand,
                model_code=model,
            )

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

            # ✅ Başarılı: payload'u al
            data = res.data or {}
            payload = data.get("label_payload", {})
            if not payload:
                MessageHandler.show(
                    self,
                    Result.fail("Label payload üretilemedi.", close_dialog=False),
                    only_errors=True
                )
                return

            # 🔽 SIRALAMA: Kullanıcının seçtiği moda göre payload'ı düzenle
            try:
                payload = sort_label_payload(payload, sort_mode)
                # Dışarıya geri verilecek Result içinde de güncel payload dursun:
                res.data["label_payload"] = payload
            except Exception as e:
                # Sıralama fail ederse, kullanıcıya bilgi ver ama orijinal sırayla devam et istersen
                MessageHandler.show(
                    self,
                    Result.fail(
                        f"Sıralama sırasında bir hata oluştu. Orijinal sıra kullanılacak.\n\n{map_error_to_message(e)}",
                        close_dialog=False
                    ),
                    only_errors=True
                )

            # --- Word template & output yolu ---
            base_dir = Path.cwd()
            template_path = base_dir / "Labels" / "assets" / f"{model}.docx"

            if not template_path.exists():
                MessageHandler.show(
                    self,
                    Result.fail(
                        f"Word şablonu bulunamadı:\n{template_path}",
                        close_dialog=False
                    ),
                    only_errors=True
                )
                return

            output_dir = base_dir / "outputs" / "labels"
            output_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"labels_{model}_{ts}.docx"

            # 📝 Word'e bas
            export_res = export_labels_to_word(
                label_payload=payload,
                template_path=str(template_path),
                output_path=str(output_path),
            )

            if not export_res or not isinstance(export_res, Result) or not export_res.success:
                MessageHandler.show(
                    self,
                    export_res if isinstance(export_res, Result) else Result.fail(
                        "Word çıktısı oluşturulurken hata oluştu.",
                        close_dialog=False
                    ),
                    only_errors=True
                )
                return

            # 🧪 İSTEĞE BAĞLI: ilk sayfanın payload özetini göster (debug)
            pages = payload.get("pages", [])
            first_page = pages[0] if pages else []

            preview_dict = {
                "brand_code": payload.get("brand_code"),
                "model_code": payload.get("model_code"),
                "max_items_per_label": payload.get("max_items_per_label"),
                "labels_per_page": payload.get("labels_per_page"),
                "total_labels": payload.get("total_labels"),
                "total_pages": payload.get("total_pages"),
                "first_page": first_page,
                "output_path": str(output_path),
                "sort_mode": sort_mode,
            }

            txt = json.dumps(preview_dict, ensure_ascii=False, indent=2)
            self._show_text_dump("Label Payload + Word Çıktısı (TEST)", txt)

            # Info mesajı
            MessageHandler.show(
                self,
                Result.ok(
                    f"Word etiket dosyası oluşturuldu:\n{output_path}",
                    close_dialog=False
                ),
                only_errors=False
            )

            # Son olarak Result'ı sakla (ileride tekrar lazım olabilir)
            self.label_result = res
            self.accept()

        except Exception as e:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(e), error=e, close_dialog=False),
                only_errors=True
            )
