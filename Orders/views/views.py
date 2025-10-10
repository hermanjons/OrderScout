from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
    QListWidget, QPushButton, QLineEdit, QComboBox, QGridLayout, QDateEdit, QCheckBox, QListWidgetItem
)

from PyQt6.QtCore import Qt, QDate, QTimer

from Core.views.views import (
    CircularProgressButton, PackageButton
)
from datetime import datetime, date
from Orders.views.actions import (
    get_orders_from_companies, collect_selected_orders,
    update_selected_count_label, load_ready_to_ship_orders, extract_cargo_names, build_order_list,
    filter_orders, refresh_cargo_filter, start_filter_worker
)

from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message

from Account.views.views import CompanyListWidget

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QHBoxLayout, QGridLayout,
    QLineEdit, QComboBox, QLabel, QListWidget, QPushButton, QDateEdit
)
from PyQt6.QtCore import QDate
from datetime import datetime, date
from Orders.signals.signals import order_signals
from Core.views.views import SwitchButton, ListSmartItemWidget
from Core.threads.sync_worker import SyncWorker


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

    # =========================
    # Yaşam döngüsü
    # =========================
    def showEvent(self, event):
        """Widget ilk gösterildiğinde siparişleri yükle."""
        super().showEvent(event)
        if not self.orders:  # sadece ilk kez
            self.reload_orders()

    # =========================
    # Ana işlemler
    # =========================
    def reload_orders(self):
        """DB'den siparişleri çekip listeyi yeniden oluşturur."""
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

    # =========================
    # Yardımcı işlemler
    # =========================
    def _safe_build(self, orders: list):
        """Build işlemini güvenli biçimde gerçekleştirir."""
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

    # =========================
    # Event callbacks
    # =========================
    def on_item_interaction(self, identifier, value: bool):
        """Toggle değiştiğinde seçili sayısını güncelle."""
        res = update_selected_count_label(self, None)
        MessageHandler.show(self, res, only_errors=True)

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


class OrdersManagerWindow(QWidget):
    """
    Kargoya hazır siparişleri yöneten ana pencere.

    Bu sınıf, siparişlerin:
    - filtrelenmesi (müşteri, tarih, kargo, ürün, sipariş no)
    - listelenmesi
    - toplu seçilmesi / seçimlerin temizlenmesi
    gibi işlemleri yönetir.

    Yapı:
        OrdersListWidget → Siparişlerin listelendiği özel widget
        start_filter_worker → actions.py içinden filtre iş mantığını yürütür
        refresh_cargo_filter → kargo dropdown’unu dinamik doldurur
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kargoya Hazır Siparişler")
        self.setGeometry(200, 200, 1000, 650)

        # Ana layout
        layout = QVBoxLayout(self)

        # ============================================================
        # 📃 LİSTE WIDGET — Siparişleri gösteren ana alan
        # ============================================================
        # Bu widget kendi reload, filter ve render mantığını yönetir.
        self.list_widget = OrdersListWidget(self)

        # ============================================================
        # 🔎 FİLTRE PANELİ — Kullanıcıya arama filtreleri sunar
        # ============================================================
        filter_box = QGroupBox("Filtreler")
        filter_layout = QGridLayout(filter_box)

        # --- Genel arama (her alanda arar)
        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("Genel Ara (müşteri, ürün, sipariş no, kargo...)")

        # --- Sipariş numarasına göre arama
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Sipariş No Ara...")

        # --- Kargo firmasına göre filtreleme
        self.cargo_filter = QComboBox()
        self.cargo_filter.addItem("Tümü")

        # --- Müşteri adına göre filtreleme
        self.customer_input = QLineEdit()
        self.customer_input.setPlaceholderText("Müşteri Adı Ara...")

        # --- Tarih aralığı filtreleme (isteğe bağlı)
        self.date_filter_enable = QCheckBox("Tarih filtresini uygula")
        self.date_filter_enable.setChecked(False)

        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))

        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())

        # Tarih alanlarını aktif/pasif yap
        self._toggle_date_inputs(self.date_filter_enable.isChecked())
        self.date_filter_enable.stateChanged.connect(
            lambda _: self._toggle_date_inputs(self.date_filter_enable.isChecked())
        )

        # ============================================================
        # 🕓 DEBOUNCE MEKANİZMASI
        # ============================================================
        # Kullanıcı yazarken sürekli filtreyi çalıştırmak yerine
        # 350 ms bekler, sonra çalıştırır → performans artışı.
        self.filter_timer = QTimer()
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.apply_filters)

        # Filtre alanlarını listele
        inputs = [
            self.global_search,
            self.search_input,
            self.customer_input,
            self.cargo_filter,
            self.date_filter_enable,
            self.date_from,
            self.date_to
        ]

        # Her input değiştiğinde debounce başlat
        for w in inputs:
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._trigger_debounce)
            elif isinstance(w, QCheckBox):
                w.stateChanged.connect(self._trigger_debounce)
            elif hasattr(w, "textChanged"):
                w.textChanged.connect(self._trigger_debounce)
            elif hasattr(w, "dateChanged"):
                w.dateChanged.connect(self._trigger_debounce)

        # --- Filtre kutularını layout’a yerleştir
        filter_layout.addWidget(QLabel("Genel Ara:"), 0, 0)
        filter_layout.addWidget(self.global_search, 0, 1, 1, 3)
        filter_layout.addWidget(QLabel("Sipariş No:"), 1, 0)
        filter_layout.addWidget(self.search_input, 1, 1)
        filter_layout.addWidget(QLabel("Kargo:"), 1, 2)
        filter_layout.addWidget(self.cargo_filter, 1, 3)
        filter_layout.addWidget(QLabel("Müşteri:"), 2, 0)
        filter_layout.addWidget(self.customer_input, 2, 1)
        filter_layout.addWidget(self.date_filter_enable, 2, 2)

        # --- Tarih aralığı satırı
        dates_row = QHBoxLayout()
        dates_row.addWidget(self.date_from)
        dates_row.addWidget(QLabel(" - "))
        dates_row.addWidget(self.date_to)
        filter_layout.addLayout(dates_row, 2, 3)

        # Layout’a filtre kutusunu ekle
        layout.addWidget(filter_box)
        layout.addWidget(self.list_widget)

        # ============================================================
        # 📊 SEÇİM SAYISI ETİKETİ
        # ============================================================
        self.selected_count_label = QLabel("Seçili: 0 / Toplam: 0 (Filtreli: 0)")
        layout.addWidget(self.selected_count_label)

        # ============================================================
        # 🚚 SİNYAL: Siparişler yüklendiğinde kargo filtrelerini yenile
        # ============================================================
        order_signals.orders_loaded.connect(self._refresh_cargo_filter)

        # ============================================================
        # 🧰 TOPLU İŞLEM BUTONLARI
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
        layout.addWidget(control_box)

    # ============================================================
    # 🔹 EVENTLER VE YARDIMCILAR
    # ============================================================

    def _refresh_cargo_filter(self, orders=None):
        """
        Yeni siparişler yüklendiğinde kargo combobox’ını günceller.
        Mantık actions.refresh_cargo_filter fonksiyonunda bulunur.
        """
        res = refresh_cargo_filter(self.cargo_filter, self.list_widget.orders)
        MessageHandler.show(self, res, only_errors=True)

    def _toggle_date_inputs(self, enabled: bool):
        """Tarih filtre kutularını aktif/pasif hale getirir."""
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)

    # ============================================================
    # 🕓 DEBOUNCE MEKANİZMASI
    # ============================================================

    def _trigger_debounce(self):
        """
        Kullanıcı yazmaya devam ederken filtreyi bekletir.
        350 ms boyunca başka input değişmezse filtre çalışır.
        """
        self.filter_timer.start(350)

    # ============================================================
    # 🔍 FİLTRE UYGULAMA
    # ============================================================

    def apply_filters(self):
        """
        Aktif filtre değerlerini toplayıp SyncWorker ile işlenmek üzere gönderir.
        Arka planda çalıştığı için UI donmaz.
        """
        try:
            # 1️⃣ Filtre parametrelerini oluştur
            filters = {
                "global": self.global_search.text().strip(),
                "order_no": self.search_input.text().strip(),
                "cargo": self.cargo_filter.currentText(),
                "customer": self.customer_input.text().strip(),
                "date_enabled": self.date_filter_enable.isChecked(),
                "date_from": self.date_from.date().toPyDate(),
                "date_to": self.date_to.date().toPyDate(),
            }

            # 2️⃣ Kullanıcıya bilgi ver
            self.selected_count_label.setText("🔄 Filtre uygulanıyor...")

            # 3️⃣ actions.start_filter_worker → arka plan işlemini başlat
            self.filter_worker = start_filter_worker(self, self.list_widget, filters)
            self.filter_worker.start()

        except Exception as e:
            msg = map_error_to_message(e)
            MessageHandler.show(self, Result.fail(msg, error=e), only_errors=True)

    # ============================================================
    # 📈 SEÇİM SAYISI GÜNCELLEME
    # ============================================================

    def _update_label(self):
        """Seçili, toplam ve filtreli sipariş sayılarını günceller."""
        selected = collect_selected_orders(self.list_widget).data.get("selected_orders", [])
        total = len(self.list_widget.orders)
        filtered = len(self.list_widget.filtered_orders)
        self.selected_count_label.setText(f"Seçili: {len(selected)} / Toplam: {total} (Filtreli: {filtered})")

    # ============================================================
    # 🧰 TOPLU SEÇİM İŞLEMLERİ
    # ============================================================

    def select_all(self):
        """Listedeki tüm siparişleri seçili hale getirir."""
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            if widget and hasattr(widget, "right_widget") and not widget.right_widget.isChecked():
                widget.right_widget.setChecked(True)
        self._update_label()

    def deselect_all(self):
        """Listedeki tüm siparişlerin seçimini kaldırır."""
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            if widget and hasattr(widget, "right_widget") and widget.right_widget.isChecked():
                widget.right_widget.setChecked(False)
        self._update_label()

    def get_selected_orders(self):
        """Seçili siparişlerin kimliklerini (orderNumber) döndürür."""
        res = collect_selected_orders(self.list_widget)
        MessageHandler.show(self, res, only_errors=True)
        if res.success:
            return res.data.get("selected_orders", [])
        return []


class OrdersTab(QWidget):
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

    # 📌 Siparişleri getir
    # views.py
    def get_orders(self):
        result = get_orders_from_companies(self, self.company_list, self.fetch_button)

        if not result.success:
            # 🔴 Progress barı hata moduna al
            print("buradan fırladı")
            self.fetch_button.fail()
            # Hata mesajını göster
            MessageHandler.show(self, result, only_errors=True)
            return

        # ⏳ işlem başladı bilgisi UI’ya yazılsın
        self.info_label.setText("⏳ Veri çekiliyor...")

    # 📌 Sipariş penceresi aç
    def open_orders_window(self):
        self.orders_window = OrdersManagerWindow()
        self.orders_window.show()

    # 📌 İşlem bittiğinde
    def on_orders_failed(self, result: Result, button: CircularProgressButton):
        """
        Worker zincirinden gelen hatalarda çalışır.
        Progress butonunu sıfırlar, kullanıcıya hata mesajı gösterir.
        """
        # 🔴 Progress butonu kırmızıya dönsün
        button.fail()

        # ❌ Hata mesajı popup olarak gösterilsin
        MessageHandler.show(self, result, only_errors=True)

        # ℹ️ UI'daki bilgi metni güncellensin
        self.info_label.setText("⚠️ İşlem başarısız.")

    def on_orders_fetched(self, result: Result):
        """
        Hem API hem DB başarılıysa çalışır.
        Kullanıcıya başarı mesajı gösterir.
        """
        # ✅ UI’ya bilgi ver
        self.info_label.setText("✅ Siparişler başarıyla kaydedildi.")

        # 🟢 Progress butonu otomatik olarak resetlenecek zaten
        # çünkü %100'e ulaşınca CircularProgressButton reset() çağırıyor.

        # ✅ İstersen log, bildirim vb. ekleyebilirsin
        # print("İşlem tamamlandı:", result.message)
