from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
    QListWidget, QPushButton
)
from PyQt6.QtCore import Qt

from Core.views.views import (
    CircularProgressButton, PackageButton
)

from Orders.views.actions import (
    get_orders_from_companies, collect_selected_orders,
    update_selected_count_label, fetch_ready_to_ship_orders, build_orders_list
)

from Feedback.processors.pipeline import MessageHandler,Result

from Account.views.views import CompanyListWidget


class OrdersListWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kargoya Hazır Siparişler")
        self.setGeometry(200, 200, 900, 600)

        layout = QVBoxLayout(self)

        # ✅ Snapshot’ları çek
        self.orders = fetch_ready_to_ship_orders(self)  # DB’den snapshotları çekiyor

        # ✅ Seçili sipariş sayısı label
        self.selected_count_label = QLabel("Seçili sipariş sayısı: 0")
        layout.addWidget(self.selected_count_label)

        # ✅ Liste widget
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self.list_widget)

        # ✅ Siparişleri listeye inşa et
        res = build_orders_list(
            self.list_widget,
            self.orders,
            self.on_item_interaction,
            self.clear_other_selections
        )
        MessageHandler.show(self, res, only_errors=True)  # sadece hata varsa popup göster

        # ✅ Toplu işlem butonları
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

    # 🔘 Switch toggle edildiğinde
    def on_item_interaction(self, identifier, value: bool):
        res = update_selected_count_label(self.list_widget, self.selected_count_label)
        MessageHandler.show(self, res, only_errors=True)

    # 🔘 Tümünü seç
    def select_all(self):
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            if widget and widget.right_widget.isChecked() is False:
                widget.right_widget.setChecked(True)

        res = update_selected_count_label(self.list_widget, self.selected_count_label)
        MessageHandler.show(self, res, only_errors=True)

    # 🔘 Seçimi kaldır
    def deselect_all(self):
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            if widget and widget.right_widget.isChecked():
                widget.right_widget.setChecked(False)

        res = update_selected_count_label(self.list_widget, self.selected_count_label)
        MessageHandler.show(self, res, only_errors=True)

    # 🔘 Tek seçim modu
    def clear_other_selections(self, keep_widget):
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            if widget is not keep_widget:
                widget.set_selected(False)

    # 🔘 İstendiğinde seçili siparişleri al
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

        # ✅ Şirketleri DB’den yükle
        result = self.company_list.build_from_db()
        MessageHandler.show(self, result, only_errors=True)

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
        self.orders_window = OrdersListWindow()
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




