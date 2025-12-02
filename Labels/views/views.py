from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QGroupBox, QPushButton, QTextEdit, QDialogButtonBox, QFileDialog, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon  # 🆕 pencere ve buton ikonu için

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
from Core.views.views import CircularProgressButton
from Core.threads.sync_worker import SyncWorker

from time import time

from Orders.models.trendyol.trendyol_models import OrderHeader
from Core.utils.model_utils import update_records
from Orders.signals.signals import order_signals


class LabelPrintManagerWindow(QDialog):
    """
    Etiket yazdırma / Word çıkartma yönetim ekranı.
    """

    progress_changed = pyqtSignal(int)  # worker → UI progress

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            # 🖨️ Pencere başlığı + ikon
            self.setWindowTitle("Etiket Yazdırma / Word Çıkart")
            # proje yapına göre yolu ayarlarsın, ben images/ altına koydun varsaydım
            self.setWindowIcon(QIcon("images/print_extract.ico"))
            self.setModal(True)
            self.setMinimumSize(450, 280)

            self.label_result: Result | None = None  # dışarıya veri taşımak için

            # worker ve geçici state
            self._worker: SyncWorker | None = None
            self._current_payload: dict | None = None
            self._current_sort_mode: str = "none"
            self._current_output_path: Path | None = None

            # progress sinyalini butona bağla
            self.progress_changed.connect(self._on_progress_changed)

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
            self.sort_combo.addItem("Orijinal sıra", userData="none")
            self.sort_combo.addItem("Ürün adına göre", userData="product")
            self.sort_combo.addItem("Adete göre", userData="quantity")
            self.sort_combo.addItem("Optimal (ürün + adet)", userData="optimal")

            row_sort.addWidget(self.sort_combo, stretch=1)
            selection_layout.addLayout(row_sort)

            main_layout.addWidget(selection_box)

            # ==============================
            # 🔘 Word Çıkart Butonu (CircularProgressButton)
            # ==============================
            buttons_layout = QHBoxLayout()
            buttons_layout.setContentsMargins(0, 8, 0, 0)
            buttons_layout.addStretch()

            self.export_button = CircularProgressButton(" Word Çıkart", parent=self)
            self.export_button.setDefault(True)
            # 🖨️ Butona da aynı icon
            self.export_button.setIcon(QIcon("images/print_extract.ico"))
            self.export_button.clicked.connect(self._on_export_clicked)

            buttons_layout.addWidget(self.export_button)
            main_layout.addLayout(buttons_layout)

            # ==============================
            # 🔄 Combobox doldurma
            # ==============================
            self._populate_brands()
            self.brand_combo.currentIndexChanged.connect(self._on_brand_changed)

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

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
        data = self.sort_combo.currentData()
        return data or "none"

    # --------------------------------------------------------
    # Progress sinyal handler
    # --------------------------------------------------------
    def _on_progress_changed(self, pct: int):
        try:
            self.export_button.setProgress(pct)
        except Exception:
            pass

    # --------------------------------------------------------
    # Word Çıkart butonu handler (thread'li)
    # --------------------------------------------------------
    def _on_export_clicked(self):
        """
        Akış aynı, sadece artık Orders tarafındaki
        collect_selected_orders tüm sayfalardaki seçimleri görecek.
        """
        try:
            if self._worker is not None and self._worker.isRunning():
                return

            brand = self.get_selected_brand_code()
            model = self.get_selected_model_code()

            if not brand or not model:
                MessageHandler.show(
                    self,
                    Result.fail("Lütfen marka ve model seçiniz.", close_dialog=False),
                    only_errors=True
                )
                self.export_button.reset()
                return

            # Seçili sipariş var mı? (model tabanlı kontrol)
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
                self.export_button.fail()
                return

            list_widget = parent.list_widget
            selected_orders = []
            if hasattr(list_widget, "get_selected_orders"):
                selected_orders = list_widget.get_selected_orders() or []

            if not selected_orders:
                MessageHandler.show(
                    self,
                    Result.fail("En az bir sipariş seçmelisiniz.", close_dialog=False),
                    only_errors=True
                )
                self.export_button.reset()
                return

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            suggested_name = f"labels_{model}_{ts}.docx"

            base_dir = Path.cwd()
            default_dir = base_dir / "outputs" / "labels"
            default_dir.mkdir(parents=True, exist_ok=True)

            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Word etiket dosyasını kaydet",
                str(default_dir / suggested_name),
                "Word Dosyası (*.docx)"
            )

            if not file_path:
                self.export_button.reset()
                return

            sort_mode = self.get_sort_mode()

            # 🌕 Butonu başlat
            self.export_button.start()
            self.progress_changed.emit(0)
            QApplication.processEvents()

            # 1) LABEL PAYLOAD → MAIN THREAD
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
                self.export_button.fail()
                return

            if not res.success:
                MessageHandler.show(self, res, only_errors=True)
                self.export_button.fail()
                return

            self.progress_changed.emit(10)
            QApplication.processEvents()

            data = res.data or {}
            payload = data.get("label_payload", {})
            if not payload:
                MessageHandler.show(
                    self,
                    Result.fail("Label payload üretilemedi.", close_dialog=False),
                    only_errors=True
                )
                self.export_button.fail()
                return

            # SIRALAMA → MAIN THREAD
            try:
                payload = sort_label_payload(payload, sort_mode)
                res.data["label_payload"] = payload
            except Exception as e:
                MessageHandler.show(
                    self,
                    Result.fail(
                        f"Sıralama sırasında bir hata oluştu. Orijinal sıra kullanılacak.\n\n{map_error_to_message(e)}",
                        close_dialog=False
                    ),
                    only_errors=True
                )
            self.progress_changed.emit(15)
            QApplication.processEvents()

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
                self.export_button.fail()
                return

            output_path = Path(file_path)

            self._current_payload = payload
            self._current_sort_mode = sort_mode
            self._current_output_path = output_path
            self.label_result = res

            def progress_cb(pct: int):
                self.progress_changed.emit(pct)

            self._worker = SyncWorker(
                export_labels_to_word,
                label_payload=payload,
                brand_code=brand,
                model_code=model,
                output_path=str(output_path),
                template_path=str(template_path),
                progress_cb=progress_cb,
            )
            self._worker.result_ready.connect(self._on_export_worker_result)
            self._worker.finished.connect(self._on_export_worker_finished)
            self._worker.start()

        except Exception as e:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(e), error=e, close_dialog=False),
                only_errors=True
            )
            try:
                self.export_button.fail()
            except Exception:
                pass

    # --------------------------------------------------------
    # Worker callback'leri
    # --------------------------------------------------------
    def _on_export_worker_result(self, result: Result):
        try:
            if not result or not isinstance(result, Result):
                MessageHandler.show(
                    self,
                    Result.fail("Word çıktısı oluşturulurken beklenmeyen bir yanıt alındı.",
                                close_dialog=False),
                    only_errors=True
                )
                self.export_button.fail()
                return

            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self.export_button.fail()
                return

            self.progress_changed.emit(100)

            # ⬇ OrderHeader flag update
            try:
                lr_data = (self.label_result.data or {}) if self.label_result else {}
                order_numbers = lr_data.get("order_numbers", []) or []

                if order_numbers:
                    now_ts = int(time() * 1000)
                    for ord_no in order_numbers:
                        upd_res = update_records(
                            model=OrderHeader,
                            filters={"orderNumber": ord_no},
                            update_data={
                                "is_extracted": True,
                                "extracted_at": now_ts,
                            },
                        )
                        if not upd_res.success:
                            print(f"[OrderHeader update error] {ord_no} → {upd_res.message}")
            except Exception as e:
                print("OrderHeader flag update error:", e)

            # ✅ Preview popup kaldırıldı

            MessageHandler.show(
                self,
                Result.ok(
                    f"Word etiket dosyası oluşturuldu:\n{self._current_output_path}",
                    close_dialog=False
                ),
                only_errors=False
            )

            order_signals.orders_changed.emit()
            self.accept()

        except Exception as e:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(e), error=e, close_dialog=False),
                only_errors=True
            )
            self.export_button.fail()

    def _on_export_worker_finished(self):
        self._worker = None
