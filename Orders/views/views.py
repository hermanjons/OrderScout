from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton
)
from PyQt6.QtCore import Qt

from Core.views.views import (
    CircularProgressButton, SwitchButton,
    ListSmartItemWidget, PackageButton
)

from Orders.views.actions import (
    fetch_with_worker, populate_company_list,
    get_company_names_from_db, get_api_credentials_by_names,
    get_orders_from_companies, collect_selected_orders,
    update_selected_count_label,fetch_ready_to_ship_orders, build_orders_list
)

from Core.utils.model_utils import get_engine
from Orders.models.trendyol_models import OrderData

from Feedback.processors.pipeline import MessageHandler,Result

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

        # 🔴 Şirket listesi
        self.active_companies = set()
        self.company_list = QListWidget()
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
        comp_list = get_company_names_from_db()
        # ✅ Şirketleri yükle
        populate_company_list(self.company_list, comp_list, self.toggle_company)  # ← kendi şirketlerini ekle



    def toggle_company(self, name: str, active: bool):
        if active:
            self.active_companies.add(name)
        else:
            self.active_companies.discard(name)

        print("Aktif şirketler:", list(self.active_companies))

    def get_orders(self):
        if not self.active_companies:
            self.info_label.setText("⚠️ Hiçbir şirket seçili değil.")
            return

        self.info_label.setText("⏳ Veri çekiliyor...")
        get_orders_from_companies(self, list(self.active_companies))

    def open_orders_window(self):
        self.orders_window = OrdersListWindow()
        self.orders_window.show()

    def on_orders_fetched(self):
        self.info_label.setText("✅ Siparişler başarıyla alındı.")


    def update_progress(self, current, total):
        percent = int(current / total * 100)
        self.fetch_button.setProgress(percent)
