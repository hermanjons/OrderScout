from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
    QListWidget, QListWidgetItem,QTableView, QLineEdit,QHeaderView ,QPushButton,QAbstractItemView, QStyledItemDelegate
)
from PyQt6.QtCore import Qt,QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from Core.views.views import CircularProgressButton, SwitchButton, ListSmartItemWidget,PackageButton
from Orders.views.actions import fetch_with_worker, populate_company_list, get_company_names_from_db, \
    get_api_credentials_by_names

from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Orders.models.trendyol_models import OrderData







from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout, QGroupBox
)
from sqlmodel import Session, select
from Core.utils.model_utils import get_engine
from Orders.models.trendyol_models import OrderData
from Core.views.views import SwitchButton, ListSmartItemWidget


class OrdersListWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kargoya Hazır Siparişler")
        self.setGeometry(200, 200, 900, 600)

        self.selected_orders = set()

        layout = QVBoxLayout(self)

        # ✅ Snapshot’ları çek → filtrele
        with Session(get_engine("orders.db")) as session:
            raw_data = session.exec(select(OrderData)).all()

        latest_snapshots = {}
        for record in raw_data:
            key = record.orderNumber
            if (
                key not in latest_snapshots or
                record.lastModifiedDate > latest_snapshots[key].lastModifiedDate
            ):
                latest_snapshots[key] = record

        filtered_data = [
            rec for rec in latest_snapshots.values()
            if rec.shipmentPackageStatus == "ReadyToShip"
        ]

        self.orders = filtered_data

        # ✅ Liste
        self.list_widget = QListWidget()
        # seçim highlight kapatılıyor, sadece hover/klik stili gözüksün
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self.list_widget)

        # Satırları doldur
        for order in self.orders:
            switch = SwitchButton()
            item_widget = ListSmartItemWidget(
                title=f"Order: {order.orderNumber}",
                subtitle=f"Müşteri: {getattr(order, 'customerFirstName', '—')} {getattr(order, 'customerLastName', '')}",
                extra=f"Kargo: {order.cargoProviderName or '-'} | Tutar: {getattr(order, 'totalPrice', 0)} ₺",
                identifier=order.orderNumber,
                icon_path="images/orders_img.png",
                optional_widget=switch
            )

            item_widget.interaction.connect(self.on_item_interaction)
            item_widget.selectionRequested.connect(self.clear_other_selections)  # 🔴 ekle

            item = QListWidgetItem(self.list_widget)
            item.setSizeHint(item_widget.sizeHint())
            self.list_widget.setItemWidget(item, item_widget)

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
    def on_item_interaction(self, identifier, value):
        if value:  # switch açık
            self.selected_orders.add(identifier)
        else:
            self.selected_orders.discard(identifier)

    # 🔘 Tümünü seç
    def select_all(self):
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            if isinstance(widget.right_widget, SwitchButton):
                widget.right_widget.setChecked(True)
                self.selected_orders.add(widget.identifier)

    # 🔘 Seçimi kaldır
    def deselect_all(self):
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            if isinstance(widget.right_widget, SwitchButton):
                widget.right_widget.setChecked(False)
        self.selected_orders.clear()

    def clear_other_selections(self, keep_widget):
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            if widget is not keep_widget:
                widget.set_selected(False)



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
        try:
            if not self.active_companies:
                self.info_label.setText("⚠️ Hiçbir şirket seçili değil.")
                return

            # 👇 1. Etiket: Kullanıcıya bilgi ver
            self.info_label.setText("⏳ Veri çekiliyor...")

            # 👇 2. Aktif şirket isimlerinden API bilgilerini çek
            selected_names = list(self.active_companies)  # set → list
            comp_api_account_list = get_api_credentials_by_names(selected_names)

            if not comp_api_account_list:
                self.info_label.setText("❌ Seçili şirketler için API bilgisi bulunamadı.")
                return

            # 👇 3. fetch_with_worker içine gönder
            fetch_with_worker(self, comp_api_account_list)

        except Exception as e:
            print("Hata:", e)
            self.info_label.setText("❌ Hata oluştu!")

    def open_orders_window(self):
        self.orders_window = OrdersListWindow()
        self.orders_window.show()

    def on_orders_fetched(self):
        self.info_label.setText("✅ Siparişler başarıyla alındı.")


    def update_progress(self, current, total):
        percent = int(current / total * 100)
        self.fetch_button.setProgress(percent)
