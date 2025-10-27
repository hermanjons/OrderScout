# ============================================================
# 🧠 CORE IMPORTS
# ============================================================
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
    QListWidget, QPushButton, QLineEdit, QComboBox, QGridLayout,
    QDateEdit, QCheckBox, QListWidgetItem
)
from PyQt6.QtCore import Qt, QDate, QTimer, QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from datetime import datetime, date

# Core widgets
from Core.views.views import (
    CircularProgressButton, PackageButton, SwitchButton, ListSmartItemWidget, ActionPulseButton
)
from Core.threads.sync_worker import SyncWorker

# ============================================================
# 🧩 DOMAIN IMPORTS
# ============================================================
from Orders.signals.signals import order_signals
from Orders.views.actions import (
    get_orders_from_companies,
    collect_selected_orders,
    load_ready_to_ship_orders,
    extract_cargo_names,
    build_order_list,
    filter_orders,
    refresh_cargo_filter,
    start_filter_worker
)
from Labels.views.views import LabelPrintManagerWindow

from Account.views.views import CompanyListWidget
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message


# ============================================================
# 🔹 1. OrdersListWidget — Sipariş Listeleme Bileşeni
# ============================================================
# Bu sınıf liste görünümünü yönetir:
# - DB’den siparişleri çeker
# - Arka planda yeniden yükleme sinyallerini dinler
# - Filtrelenmiş veya tüm siparişleri render eder
# ============================================================

class OrdersListWidget(QListWidget):
    """
    Siparişleri göstermek için optimize edilmiş özel liste widget'i.
    - Gösterildiğinde kendini otomatik yükler.
    - Sinyal geldiğinde yeniden yükler.
    - Filtreli sonuçları kendisi uygular.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.orders: list = []
        self.filtered_orders: list = []

        # 🔌 Siparişler değiştiğinde kendini yenile
        order_signals.orders_changed.connect(self.reload_orders)

    # ============================================================
    # 🔄 Yaşam Döngüsü
    # ============================================================
    def showEvent(self, event):
        """Widget ilk gösterildiğinde siparişleri yükle."""
        super().showEvent(event)
        if not self.orders:  # sadece ilk kez
            self.reload_orders()

    # ============================================================
    # 🧩 Ana İşlemler
    # ============================================================
    def reload_orders(self):
        """
        DB'den siparişleri çekip listeyi yeniden oluşturur.
        """
        try:
            result = load_ready_to_ship_orders()
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                return

            # 🔁 Verileri güncelle
            self.orders = result.data.get("records", [])
            self.filtered_orders = list(self.orders)

            # ✅ Listeyi inşa et
            self._safe_build(self.orders)

            # 📢 UI’ya siparişlerin yüklendiğini bildir
            order_signals.orders_loaded.emit(self.orders)

        except Exception as e:
            msg = map_error_to_message(e)
            MessageHandler.show(self, Result.fail(msg, error=e), only_errors=True)

    def apply_filter_result(self, filtered_orders: list):
        """Filtrelenmiş sipariş listesini uygular (yeniden çizim)."""
        self.filtered_orders = filtered_orders
        self._safe_build(filtered_orders)

    # ============================================================
    # 🧰 Yardımcı İşlemler
    # ============================================================
    def _safe_build(self, orders: list):
        """
        Build işlemini güvenli biçimde gerçekleştirir.
        Memory leak koruması içerir.
        """
        try:
            # 🧹 Gereksiz render engelleme
            if not orders and not self.count():
                return

            # 🧽 Qt memory leak koruması
            for i in range(self.count()):
                widget = self.itemWidget(self.item(i))
                if widget:
                    widget.deleteLater()
            self.clear()

            # 🏗️ Listeyi actions.py'deki builder ile inşa et
            result = build_order_list(self, orders, self.on_item_interaction, self.clear_other_selections)
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)

        except Exception as e:
            msg = map_error_to_message(e)
            MessageHandler.show(self, Result.fail(msg, error=e), only_errors=True)

    # ============================================================
    # 🎯 Event Callbacks
    # ============================================================
    def on_item_interaction(self, identifier, value: bool):
        """Toggle değiştiğinde seçili sayısını güncelle."""
        pass

    def clear_other_selections(self, keep_widget):
        """Tek seçim modu: diğer seçimleri temizle."""
        for i in range(self.count()):
            widget = self.itemWidget(self.item(i))
            if widget is not keep_widget and hasattr(widget, "set_selected"):
                widget.set_selected(False)

    def get_selected_orders(self) -> list:
        """Seçili siparişleri döndür."""
        res = collect_selected_orders(self)
        if res.success:
            return res.data.get("selected_orders", [])
        return []


# ============================================================
# 🔹 2. OrdersManagerWindow — Filtreleme Penceresi
# ============================================================
# Bu pencere:
# - Filtre alanlarını (müşteri, kargo, tarih, sipariş no) içerir
# - Debounce mekanizması ile performanslı filtreleme yapar
# - Listeyi güncel tutar
# ============================================================

class OrdersManagerWindow(QWidget):
    """
    Kargoya hazır siparişleri yöneten ana pencere.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kargoya Hazır Siparişler")
        self.setGeometry(200, 200, 1000, 650)

        # === ANA LAYOUT ARTIK YATAY ===
        main_layout = QHBoxLayout(self)

        # SOL PANEL: filtreler + liste + sayaç + toplu seçim
        left_panel = QVBoxLayout()
        main_layout.addLayout(left_panel, stretch=1)

        # SAĞ PANEL: aksiyon butonu
        right_panel = QVBoxLayout()
        right_panel.setContentsMargins(10, 10, 10, 10)
        right_panel.setSpacing(20)
        main_layout.addLayout(right_panel, stretch=0)

        # ============================================================
        # 📦 Liste Widget
        # ============================================================
        self.list_widget = OrdersListWidget(self)

        # ============================================================
        # 🔍 Filtre Paneli
        # ============================================================
        filter_box = QGroupBox("Filtreler")
        filter_layout = QGridLayout(filter_box)

        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("Genel Ara (müşteri, ürün, sipariş no, kargo...)")

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Sipariş No Ara...")
        numeric_validator = QRegularExpressionValidator(QRegularExpression(r"^\d*$"))
        self.search_input.setValidator(numeric_validator)

        self.cargo_filter = QComboBox()
        self.cargo_filter.addItem("Tümü")

        self.customer_input = QLineEdit()
        self.customer_input.setPlaceholderText("Müşteri Adı Ara...")

        self.date_filter_enable = QCheckBox("Tarih filtresini uygula")
        self.date_filter_enable.setChecked(False)

        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd.MM.yyyy")
        self.date_from.setFixedWidth(130)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))

        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd.MM.yyyy")
        self.date_to.setFixedWidth(130)
        self.date_to.setDate(QDate.currentDate())

        self.date_from.setStyleSheet("QDateEdit { padding: 3px; border-radius: 4px; }")
        self.date_to.setStyleSheet("QDateEdit { padding: 3px; border-radius: 4px; }")

        self._toggle_date_inputs(self.date_filter_enable.isChecked())
        self.date_filter_enable.stateChanged.connect(
            lambda _: self._toggle_date_inputs(self.date_filter_enable.isChecked())
        )

        # Debounce timer
        self.filter_timer = QTimer()
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.apply_filters)

        # filtre input'larını debounce'a bağla
        inputs = [
            self.global_search, self.search_input, self.customer_input,
            self.cargo_filter, self.date_filter_enable, self.date_from, self.date_to
        ]
        for w in inputs:
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._trigger_debounce)
            elif isinstance(w, QCheckBox):
                w.stateChanged.connect(self._trigger_debounce)
            elif hasattr(w, "textChanged"):
                w.textChanged.connect(self._trigger_debounce)
            elif hasattr(w, "dateChanged"):
                w.dateChanged.connect(self._trigger_debounce)

        # filtre layout yerleşimi
        filter_layout.addWidget(QLabel("Genel Ara:"), 0, 0)
        filter_layout.addWidget(self.global_search, 0, 1, 1, 3)
        filter_layout.addWidget(QLabel("Sipariş No:"), 1, 0)
        filter_layout.addWidget(self.search_input, 1, 1)
        filter_layout.addWidget(QLabel("Kargo:"), 1, 2)
        filter_layout.addWidget(self.cargo_filter, 1, 3)
        filter_layout.addWidget(QLabel("Müşteri:"), 2, 0)
        filter_layout.addWidget(self.customer_input, 2, 1)
        filter_layout.addWidget(self.date_filter_enable, 2, 2)

        dates_row = QHBoxLayout()
        dates_row.addWidget(self.date_from)
        dates_row.addWidget(QLabel(" - "))
        dates_row.addWidget(self.date_to)
        dates_row.addStretch()
        filter_layout.addLayout(dates_row, 2, 3)

        # sol panel'e ekle
        left_panel.addWidget(filter_box)
        left_panel.addWidget(self.list_widget)

        # ============================================================
        # 📊 Seçim Bilgisi
        # ============================================================
        self.selected_count_label = QLabel("Seçili: 0 / Toplam: 0 (Filtreli: 0)")
        left_panel.addWidget(self.selected_count_label)

        # ============================================================
        # 🚚 Sipariş Yüklendiğinde
        # ============================================================
        order_signals.orders_loaded.connect(self._refresh_cargo_filter)
        order_signals.orders_loaded.connect(self._update_label)
        order_signals.orders_loaded.connect(self._update_action_button_state)

        # ============================================================
        # 🧰 Toplu İşlemler
        # ============================================================
        control_box = QGroupBox("Toplu İşlemler")
        control_layout = QHBoxLayout(control_box)

        select_all_btn = QPushButton("Tümünü Seç")
        deselect_all_btn = QPushButton("Seçimi Kaldır")
        select_all_btn.clicked.connect(self.select_all)
        deselect_all_btn.clicked.connect(self.deselect_all)

        control_layout.addStretch()
        control_layout.addWidget(select_all_btn)
        control_layout.addWidget(deselect_all_btn)

        left_panel.addWidget(control_box)

        # ============================================================
        # 👉 Sağ Panel: Aksiyon Butonu
        # ============================================================
        self.action_button = ActionPulseButton(text="Yazdır")
        # self.action_button.setIconPixmap(":/icons/printer.png")   # ikon eklersin
        self.action_button.setEnabled(False)  # başta kapalı
        self.action_button.clicked.connect(self._on_action_button_clicked)

        right_panel.addStretch()
        right_panel.addWidget(self.action_button, alignment=Qt.AlignmentFlag.AlignTop)
        right_panel.addStretch()

    # ============================================================
    # 🔁 Butonun aktif/pasif olması (seçime göre)
    # ============================================================
    def _update_action_button_state(self):
        selected_res = collect_selected_orders(self.list_widget)
        selected_list = []
        if selected_res.success:
            selected_list = selected_res.data.get("selected_orders", [])
        self.action_button.setEnabled(len(selected_list) > 0)

    # ============================================================
    # 🔘 Buton tıklama davranışı (ileride yazdır flow buraya girecek)
    # ============================================================
    def _on_action_button_clicked(self):
        # seçili siparişleri al
        chosen_orders = self.get_selected_orders()

        # güvenlik: hiç seçili yoksa zaten buton disable olmalı ama yine de check yapıyoruz
        if not chosen_orders:
            return

        # Label yazdırma yöneticisini aç
        # referansı self üstünde tutuyoruz ki GC hemen öldürmesin
        self.label_window = LabelPrintManagerWindow(self)
        self.label_window.show()
        self.label_window.raise_()
        self.label_window.activateWindow()

    # ============================================================
    # (geri kalan fonksiyonların değişmiyor)
    # ============================================================
    def _refresh_cargo_filter(self, orders=None):
        res = refresh_cargo_filter(self.cargo_filter, self.list_widget.orders)
        MessageHandler.show(self, res, only_errors=True)

    def _toggle_date_inputs(self, enabled: bool):
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)
        self.date_from.setStyleSheet("" if enabled else "color: gray;")
        self.date_to.setStyleSheet("" if enabled else "color: gray;")

    def _trigger_debounce(self):
        self.filter_timer.start(350)

    def apply_filters(self):
        try:
            filters = {
                "global": self.global_search.text().strip(),
                "order_no": self.search_input.text().strip(),
                "cargo": self.cargo_filter.currentText(),
                "customer": self.customer_input.text().strip(),
                "date_enabled": self.date_filter_enable.isChecked(),
                "date_from": self.date_from.date().toPyDate(),
                "date_to": self.date_to.date().toPyDate(),
            }

            self.selected_count_label.setText("🔄 Filtre uygulanıyor...")
            self.filter_worker = start_filter_worker(self, self.list_widget, filters)
            self.filter_worker.start()

        except Exception as e:
            msg = map_error_to_message(e)
            MessageHandler.show(self, Result.fail(msg, error=e), only_errors=True)

    def _update_label(self):
        selected = collect_selected_orders(self.list_widget).data.get("selected_orders", [])
        total = len(self.list_widget.orders)
        filtered = len(self.list_widget.filtered_orders)
        self.selected_count_label.setText(
            f"Seçili: {len(selected)} / Toplam: {total} (Filtreli: {filtered})"
        )
        # seçili sayısı değişince butonu da güncelle
        self._update_action_button_state()

    def select_all(self):
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            if widget and hasattr(widget, "right_widget") and not widget.right_widget.isChecked():
                widget.right_widget.setChecked(True)
        self._update_label()

    def deselect_all(self):
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            if widget and hasattr(widget, "right_widget") and widget.right_widget.isChecked():
                widget.right_widget.setChecked(False)
        self._update_label()

    def get_selected_orders(self):
        res = collect_selected_orders(self.list_widget)
        MessageHandler.show(self, res, only_errors=True)
        if res.success:
            return res.data.get("selected_orders", [])
        return []


# ============================================================
# 🔹 3. OrdersTab — Ana Tab / Veri Çekme Arayüzü
# ============================================================
# Bu kısım Trendyol API'sinden sipariş çeker, progress bar’ı yönetir,
# OrdersManagerWindow’u açar.
# ============================================================

class OrdersTab(QWidget):
    """
    OrdersManagerWindow ve veri çekme işlemini yöneten ana sekme bileşeni.
    """

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # 🟡 Üst bilgilendirme yazısı
        self.info_label = QLabel("Siparişleri buradan yönetebilirsin.")
        self.order_btn = PackageButton("Siparişler", icon_path="images/orders_img.png")
        self.order_btn.clicked.connect(self.open_orders_window)
        layout.addWidget(self.order_btn)
        layout.addWidget(self.info_label)

        # 🟢 Başlatma butonu
        self.fetch_button = CircularProgressButton("BAŞLAT")
        self.fetch_button.clicked.connect(self.get_orders)

        # 🔴 Şirket listesi → CompanyListWidget
        self.company_list = CompanyListWidget()
        self.company_list.setFixedWidth(240)

        # 🟤 Alt panel: Şirketler + Buton
        self.bottom_panel = QGroupBox("Veri Çekme Paneli")
        self.bottom_panel.setFixedHeight(200)
        bottom_layout = QHBoxLayout(self.bottom_panel)

        company_box = QGroupBox("Şirketler")
        company_layout = QVBoxLayout(company_box)
        company_layout.setContentsMargins(5, 5, 5, 5)
        company_layout.addWidget(self.company_list)
        bottom_layout.addWidget(company_box)

        btn_container = QWidget()
        btn_layout = QVBoxLayout(btn_container)
        btn_layout.addStretch()
        btn_layout.addWidget(self.fetch_button, alignment=Qt.AlignmentFlag.AlignCenter)
        btn_layout.addStretch()
        bottom_layout.addWidget(btn_container)

        layout.addWidget(self.bottom_panel)

    # ============================================================
    # 📡 Siparişleri API'den Getir
    # ============================================================
    def get_orders(self):
        """
        Seçili şirketlerden siparişleri çeker, progress'i başlatır.
        """
        result = get_orders_from_companies(self, self.company_list, self.fetch_button)
        if not result.success:
            self.fetch_button.fail()
            MessageHandler.show(self, result, only_errors=True)
            return
        self.info_label.setText("⏳ Veri çekiliyor...")

    # ============================================================
    # 🪟 Sipariş Penceresi Aç
    # ============================================================
    def open_orders_window(self):
        """Filtreleme ve listeleme penceresini açar."""
        self.orders_window = OrdersManagerWindow()
        self.orders_window.show()

    # ============================================================
    # ⚠️ Worker Callback — Hata Durumu
    # ============================================================
    def on_orders_failed(self, result: Result, button: CircularProgressButton):
        """
        Worker zincirinden gelen hatalarda çalışır.
        Progress butonunu sıfırlar, kullanıcıya hata mesajı gösterir.
        """
        button.fail()
        MessageHandler.show(self, result, only_errors=True)
        self.info_label.setText("⚠️ İşlem başarısız.")

    # ============================================================
    # ✅ Worker Callback — Başarı Durumu
    # ============================================================
    def on_orders_fetched(self, result: Result):
        """
        API ve DB işlemleri başarılı olduğunda çalışır.
        """
        self.info_label.setText("✅ Siparişler başarıyla kaydedildi.")
