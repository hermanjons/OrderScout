from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt

from Feedback.processors.pipeline import Result, map_error_to_message

# yeni düz constants importu
from Labels.constants.constants import (
    LABEL_BRANDS,
    LABEL_MODELS_BY_BRAND,
)


class LabelPrintManagerWindow(QWidget):
    """
    Etiket yazdırma yönetim ekranı.
    - Marka seç (ör: Tanex)
    - Model seç (ör: 2736)

    İleride:
    - Seçili sipariş adeti gösterilecek
    - Önizleme
    - Dışa aktar / Yazdır
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        try:
            self.setWindowTitle("Etiket Yazdırma")
            self.setMinimumSize(400, 250)

            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(16, 16, 16, 16)
            main_layout.setSpacing(16)

            # ============================================================
            # Marka / Model Seçimi
            # ============================================================
            selection_box = QGroupBox("Şablon Seçimi")
            selection_layout = QVBoxLayout(selection_box)
            selection_layout.setContentsMargins(12, 12, 12, 12)
            selection_layout.setSpacing(12)

            # --- Marka satırı
            row_brand = QHBoxLayout()
            row_brand.setSpacing(8)

            row_brand.addWidget(QLabel("Marka:"), stretch=0, alignment=Qt.AlignmentFlag.AlignVCenter)

            self.brand_combo = QComboBox()
            self.brand_combo.setEditable(False)
            row_brand.addWidget(self.brand_combo, stretch=1)

            selection_layout.addLayout(row_brand)

            # --- Model satırı
            row_model = QHBoxLayout()
            row_model.setSpacing(8)

            row_model.addWidget(QLabel("Model:"), stretch=0, alignment=Qt.AlignmentFlag.AlignVCenter)

            self.model_combo = QComboBox()
            self.model_combo.setEditable(False)
            row_model.addWidget(self.model_combo, stretch=1)

            selection_layout.addLayout(row_model)

            main_layout.addWidget(selection_box)

            # ============================================================
            # dropdown doldurma
            # ============================================================
            self._populate_brands()
            self.brand_combo.currentIndexChanged.connect(self._on_brand_changed)

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    # ------------------------------------------------------------
    # helperlar (bunlar artık view içinde kalıyor)
    # ------------------------------------------------------------
    def _populate_brands(self):
        """
        LABEL_BRANDS içeriğini brand_combo'ya doldurur.
        İlk markaya göre model listesini de çeker.
        """
        try:
            self.brand_combo.clear()

            for brand in LABEL_BRANDS:
                # brand["name"] kullanıcıya görünen
                # brand["code"] dahili
                self.brand_combo.addItem(brand["name"], userData=brand["code"])

            # ilk markaya bağlı olarak modelleri yükle
            self._populate_models_for_current_brand()

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def _on_brand_changed(self, _index: int):
        try:
            self._populate_models_for_current_brand()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def _populate_models_for_current_brand(self):
        """
        Seçili marka kodunu alır ve LABEL_MODELS_BY_BRAND'tan model listesini doldurur.
        """
        try:
            brand_code = self.brand_combo.currentData()  # örn: "TANEX"
            models = LABEL_MODELS_BY_BRAND.get(brand_code, [])

            self.model_combo.clear()
            for m in models:
                # m["name"] → kullanıcıya görünen ("2736")
                # m["code"] → içsel kod ("TANEX_2736")
                self.model_combo.addItem(m["name"], userData=m["code"])

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    # ------------------------------------------------------------
    # public getters: business logic buradan okuyacak
    # ------------------------------------------------------------
    def get_selected_brand_code(self) -> str | None:
        return self.brand_combo.currentData()

    def get_selected_model_code(self) -> str | None:
        return self.model_combo.currentData()
