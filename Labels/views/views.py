from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QGroupBox, QPushButton, QTextEdit, QDialogButtonBox, QFileDialog, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal

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
from Core.views.views import CircularProgressButton  # yolunu projene göre ayarla
from Core.threads.sync_worker import SyncWorker

from time import time

from Orders.models.trendyol.trendyol_models import OrderHeader
from Core.utils.model_utils import update_records  # ← model_utils.py nin yolu neyse ona göre düzelt


class LabelPrintManagerWindow(QDialog):
    """
    Etiket yazdırma / Word çıkartma yönetim ekranı.
    - Marka seçimi
    - Model seçimi
    - Sıralama seçimi
    - Word Çıkart butonu:
        - Seçili siparişlerden etiket datasını hazırlayan pipeline'ı tetikler.
        - export_labels_to_word işlemini ayrı bir thread'de çalıştırır.

    İşlem başarılı olursa:
        - self.label_result içinde Result nesnesi
        - self.label_result.data içinde:
            - label_payload (sıralama uygulanmış haliyle)
            - diğer sipariş verileri
        tutulur ve dialog accept() ile kapanır.
    """

    progress_changed = pyqtSignal(int)  # worker → UI progress

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.setWindowTitle("Etiket Yazdırma / Word Çıkart")
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
            # userData ile sıralama modlarını tutuyoruz
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

            self.export_button = CircularProgressButton("Word Çıkart", parent=self)
            self.export_button.setDefault(True)
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
    # Progress sinyal handler
    # --------------------------------------------------------
    def _on_progress_changed(self, pct: int):
        """Worker'dan gelen progress'i butona yansıt."""
        try:
            self.export_button.setProgress(pct)
        except Exception:
            pass

    # --------------------------------------------------------
    # Word Çıkart butonu handler (thread'li)
    # --------------------------------------------------------
    def _on_export_clicked(self):
        """
        Akış:
        0) Kullanıcıdan kaydedilecek Word dosyasının yolunu iste
        1) Marka & model & list_widget kontrolü
        2) create_order_label_from_orders → payload üret (MAIN THREAD)
        3) sort_label_payload → sıralama (MAIN THREAD)
        4) export_labels_to_word'u SyncWorker ile ayrı thread'de çalıştır
        5) progress_cb → progress_changed sinyaliyle butona yansır
        6) Worker bitince sonucu al, mesajları göster, dialog'u kapat
        """
        try:
            # Aynı anda ikinci kez çalışmasın
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

            # Varsayılan dosya adı
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

            # Kullanıcı iptal ederse
            if not file_path:
                self.export_button.reset()
                return

            sort_mode = self.get_sort_mode()

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

            # 🌕 Butonu başlat
            self.export_button.start()
            self.progress_changed.emit(0)
            QApplication.processEvents()

            # 1) LABEL PAYLOAD → MAIN THREAD (list_widget'e dokunuyoruz)
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
                # sıralama patlasa bile eski payload ile devam
            self.progress_changed.emit(15)
            QApplication.processEvents()

            # Şablon kontrolü
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

            # Bu değerleri worker tamamlandığında kullanmak için saklıyoruz
            self._current_payload = payload
            self._current_sort_mode = sort_mode
            self._current_output_path = output_path
            self.label_result = res  # payload sonucu, dialog dışına da taşımak istersen

            # Progress callback: worker thread'den çağrılacak
            def progress_cb(pct: int):
                # worker thread → sinyal → UI thread
                self.progress_changed.emit(pct)

            # 2) WORD EXPORT → WORKER THREAD
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
        """
        SyncWorker içindeki export_labels_to_word bittikten sonra gelen Result.
        Burada:
          - Sonucu kontrol ediyoruz
          - Başarılıysa OrderHeader üzerinde is_extracted / extracted_at güncelliyoruz
          - Debug dump + bilgi mesajı gösteriyoruz
        """
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

            # %100'e çek (export tarafı da 100 dese bile garanti olsun)
            self.progress_changed.emit(100)

            # ⬇⬇⬇ OrderHeader.flag update (model_utils ile) ⬇⬇⬇
            try:
                # create_order_label_from_orders içinde set ettiğimiz data
                lr_data = (self.label_result.data or {}) if self.label_result else {}
                order_numbers = lr_data.get("order_numbers", []) or []

                if order_numbers:
                    now_ts = int(time() * 1000)  # diğer timestamp alanlarınla aynı formata göre

                    for ord_no in order_numbers:
                        # Her orderNumber için update_records çağırıyoruz
                        upd_res = update_records(
                            model=OrderHeader,
                            filters={"orderNumber": ord_no},
                            update_data={
                                "is_extracted": True,
                                "extracted_at": now_ts,
                                # İleride direkt yazıcı kullanırsan:
                                # "is_printed": True,
                                # "printed_at": now_ts,
                            },
                        )
                        # Hata olursa logla ama export'u bozmuyoruz
                        if not upd_res.success:
                            print(f"[OrderHeader update error] {ord_no} → {upd_res.message}")
            except Exception as e:
                # Flag güncellemesi patlasa bile export başarısını bozmuyoruz,
                # sadece log / print yeterli.
                print("OrderHeader flag update error:", e)

            # ⬆⬆⬆ YENİ KISIM BİTTİ ⬆⬆⬆

            # Debug için payload özetini göstermek istersen:
            payload = self._current_payload or {}
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
                "output_path": str(self._current_output_path) if self._current_output_path else "",
                "sort_mode": self._current_sort_mode,
            }

            txt = json.dumps(preview_dict, ensure_ascii=False, indent=2)
            self._show_text_dump("Label Payload + Word Çıktısı (TEST)", txt)

            # Bilgi mesajı
            MessageHandler.show(
                self,
                Result.ok(
                    f"Word etiket dosyası oluşturuldu:\n{self._current_output_path}",
                    close_dialog=False
                ),
                only_errors=False
            )

            # İşlem başarılı → dialog'u kapat
            self.accept()

        except Exception as e:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(e), error=e, close_dialog=False),
                only_errors=True
            )
            self.export_button.fail()

    def _on_export_worker_finished(self):
        """Worker bittiğinde referansı bırak."""
        self._worker = None
        # CircularProgressButton 100'e geldiğinde zaten reset logic'i var;
        # fail durumunda da fail() çağrılıyor.
