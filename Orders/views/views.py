from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
    QListWidget, QPushButton, QLineEdit, QComboBox, QGridLayout, QDateEdit, QCheckBox, QListWidgetItem
)

from PyQt6.QtCore import Qt, QDate

from Core.views.views import (
    CircularProgressButton, PackageButton
)
from datetime import datetime, date
from Orders.views.actions import (
    get_orders_from_companies, collect_selected_orders,
    update_selected_count_label, fetch_ready_to_ship_orders, extract_cargo_names
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


class OrdersListWidget(QListWidget):
    """
    Siparişleri göstermek için özelleştirilmiş liste widget'i.
    İlk açıldığında DB'den siparişleri çekip kendini doldurur.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.orders: list = []
        self.filtered_orders: list = []

        # 🔌 Siparişler değişirse kendini yenile
        order_signals.orders_changed.connect(self.reload_orders)

    def showEvent(self, event):
        """Widget ilk gösterildiğinde siparişleri yükle."""
        super().showEvent(event)
        if not self.orders:  # sadece ilk kez
            self.reload_orders()

    def reload_orders(self):
        """Siparişleri DB'den çek ve listeyi yeniden inşa et."""
        self.orders = fetch_ready_to_ship_orders(self)
        self.filtered_orders = list(self.orders)
        self._build_list(self.orders)

        # 📢 UI'ya siparişler yüklendi bilgisini ver
        order_signals.orders_loaded.emit(self.orders)

    def _build_list(self, orders: list | None = None):
        """Sipariş listesini yeniden inşa et."""
        try:
            if orders is None:
                orders = self.orders
            # else: ❌ burada self.orders’ı değiştirme

            self.clear()

            if not orders:
                info_item = QListWidgetItem("Gösterilecek sipariş bulunamadı.")
                info_item.setFlags(info_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.addItem(info_item)
                return

            for order in orders:
                logo_path = "images/orders_img.png"
                if getattr(order, "api_account", None) and getattr(order.api_account, "logo_path", None):
                    logo_path = order.api_account.logo_path

                switch = SwitchButton()
                item_widget = ListSmartItemWidget(
                    title=f"Order: {getattr(order, 'orderNumber', '—')}",
                    subtitle=f"Müşteri: {getattr(order, 'customerFirstName', '—')} "
                             f"{getattr(order, 'customerLastName', '')}",
                    extra=f"Kargo: {getattr(order, 'cargoProviderName', '-')} | "
                          f"Tutar: {getattr(order, 'totalPrice', 0)} ₺",
                    identifier=getattr(order, 'orderNumber', '—'),
                    icon_path=logo_path,
                    optional_widget=switch
                )

                item_widget.interaction.connect(self.on_item_interaction)
                item_widget.selectionRequested.connect(self.clear_other_selections)

                item = QListWidgetItem(self)
                item.setSizeHint(item_widget.sizeHint())
                self.setItemWidget(item, item_widget)

        except Exception as e:
            msg = map_error_to_message(e)
            MessageHandler.show(self, Result.fail(msg, error=e), only_errors=True)

    # =========================
    # Event callbacks
    # =========================
    def on_item_interaction(self, identifier, value: bool):
        """Her toggle değiştiğinde seçili sayısını güncelle."""
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kargoya Hazır Siparişler")
        self.setGeometry(200, 200, 1000, 650)

        layout = QVBoxLayout(self)

        # =========================
        # 📃 LİSTE
        # =========================
        self.list_widget = OrdersListWidget(self)

        # =========================
        # 🔎 FİLTRE PANELİ
        # =========================
        filter_box = QGroupBox("Filtreler")
        filter_layout = QGridLayout(filter_box)

        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("Genel Ara (müşteri, ürün, sipariş no, kargo...)")
        self.global_search.textChanged.connect(self.apply_filters)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Sipariş No Ara...")
        self.search_input.textChanged.connect(self.apply_filters)

        self.cargo_filter = QComboBox()
        self.cargo_filter.addItem("Tümü")
        self.cargo_filter.currentIndexChanged.connect(self.apply_filters)

        self.customer_input = QLineEdit()
        self.customer_input.setPlaceholderText("Müşteri Adı Ara...")
        self.customer_input.textChanged.connect(self.apply_filters)

        self.date_filter_enable = QCheckBox("Tarih filtresini uygula")
        self.date_filter_enable.setChecked(False)
        self.date_filter_enable.stateChanged.connect(self.apply_filters)

        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_from.dateChanged.connect(self.apply_filters)

        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.dateChanged.connect(self.apply_filters)

        self._toggle_date_inputs(self.date_filter_enable.isChecked())
        self.date_filter_enable.stateChanged.connect(
            lambda _: self._toggle_date_inputs(self.date_filter_enable.isChecked())
        )

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
        filter_layout.addLayout(dates_row, 2, 3)

        layout.addWidget(filter_box)

        # 📊 Seçili sayısı
        self.selected_count_label = QLabel("Seçili: 0 / Toplam: 0 (Filtreli: 0)")
        layout.addWidget(self.selected_count_label)

        layout.addWidget(self.list_widget)

        # 🚚 Siparişler yüklendiğinde kargo filtrelerini doldur
        order_signals.orders_loaded.connect(self._refresh_cargo_filter)

        # 🧰 Toplu işlem butonları
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




    # =========================
    # Helpers
    # =========================
    def _toggle_date_inputs(self, enabled: bool):
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)

    def _coerce_to_date(self, v) -> date | None:
        if v is None:
            return None
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, (int, float)):
            try:
                return datetime.fromtimestamp(v).date()
            except Exception:
                return None
        if isinstance(v, str):
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(v, fmt).date()
                except Exception:
                    pass
        return None

    def _get_order_date(self, o) -> date | None:
        for attr in ("shipmentDate", "orderDate", "createdDate"):
            d = self._coerce_to_date(getattr(o, attr, None))
            if d:
                return d
        return None

    def _refresh_cargo_filter(self, orders=None):
        """Siparişler yüklendikten sonra kargo firmalarını doldur."""
        self.cargo_filter.blockSignals(True)  # 🔇 geçici olarak sinyali kapat
        self.cargo_filter.clear()
        self.cargo_filter.addItem("Tümü")
        cargos = extract_cargo_names(self.list_widget.orders)
        self.cargo_filter.addItems(cargos)
        self.cargo_filter.blockSignals(False)  # 🔊 geri aç

    # =========================
    # Filtreleri uygula
    # =========================
    def apply_filters(self):
        # 🔥 her zaman full liste üzerinden filtre başlasın
        filtered = list(self.list_widget.orders)

        search_text = self.search_input.text().strip().lower()
        cargo_text = self.cargo_filter.currentText()
        customer_text = self.customer_input.text().strip().lower()
        global_text = self.global_search.text().strip().lower()

        if global_text:
            new_list = []
            for o in filtered:
                items = getattr(o, "items", None) or []
                in_items = any(
                    global_text in str(getattr(it, "productName", "")).lower()
                    or global_text in str(getattr(it, "productSku", "")).lower()
                    for it in items
                )
                if (
                    global_text in str(getattr(o, "orderNumber", "")).lower()
                    or global_text in str(getattr(o, "cargoProviderName", "")).lower()
                    or global_text in str(getattr(o, "customerFirstName", "")).lower()
                    or in_items
                ):
                    new_list.append(o)
            filtered = new_list

        if search_text:
            filtered = [o for o in filtered if search_text in str(getattr(o, "orderNumber", "")).lower()]

        if cargo_text and cargo_text != "Tümü":
            filtered = [o for o in filtered if getattr(o, "cargoProviderName", None) == cargo_text]

        if customer_text:
            filtered = [o for o in filtered if customer_text in str(getattr(o, "customerFirstName", "")).lower()]

        if self.date_filter_enable.isChecked():
            df = self.date_from.date().toPyDate()
            dt = self.date_to.date().toPyDate()
            tmp = []
            for o in filtered:
                od = self._get_order_date(o)
                if od and df <= od <= dt:
                    tmp.append(o)
            filtered = tmp

        # 🔥 filtre sonucunu widget'a gönder
        self.list_widget.filtered_orders = filtered
        self.list_widget._build_list(filtered)
        self._update_label()

    # =========================
    # Seçili sayısı güncelle
    # =========================
    def _update_label(self):
        selected = collect_selected_orders(self.list_widget).data.get("selected_orders", [])
        total = len(self.list_widget.orders)
        filtered = len(self.list_widget.filtered_orders)
        self.selected_count_label.setText(f"Seçili: {len(selected)} / Toplam: {total} (Filtreli: {filtered})")

    # =========================
    # Toplu seçimler
    # =========================
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
