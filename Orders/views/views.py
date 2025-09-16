from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
    QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt
from Core.views.views import CircularProgressButton, SwitchButton, ListSmartItemWidget
from Orders.views.actions import fetch_with_worker, populate_company_list, get_company_names_from_db, \
    get_api_credentials_by_names






from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTableView, QLineEdit, QHBoxLayout,
    QGroupBox, QHeaderView
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from sqlmodel import Session, select
from Core.utils.model_utils import get_engine
from Orders.models.trendyol_models import OrderData
from collections import defaultdict


# 🔹 ORM verisini tabloya bağlayan model
class SQLModelTableModel(QAbstractTableModel):
    def __init__(self, records, columns, parent=None):
        super().__init__(parent)
        self.records = records
        self.columns = columns

    def rowCount(self, parent=QModelIndex()):
        return len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            record = self.records[index.row()]
            col_name = self.columns[index.column()]
            return str(getattr(record, col_name, ""))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section]
        return None


# 🔹 Çoklu filtre desteği
class MultiFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filters = {}

    def setFilterForColumn(self, column, text):
        self.filters[column] = text.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        for column, text in self.filters.items():
            if text:
                index = self.sourceModel().index(source_row, column, source_parent)
                data = str(self.sourceModel().data(index, Qt.ItemDataRole.DisplayRole)).lower()
                if text not in data:
                    return False
        return True


# 🔹 Pencere sınıfı
class OrdersListWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kargoya Hazır Siparişler")
        self.setGeometry(200, 200, 1000, 600)

        layout = QVBoxLayout(self)

        # ✅ Veriyi çek ve filtrele
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

        # ✅ shipmentPackageStatus filtresi
        filtered_data = [
            rec for rec in latest_snapshots.values()
            if rec.shipmentPackageStatus == "ReadyToShip"
        ]

        # ✅ Gösterilecek kolonlar
        columns = [
            "orderNumber",
            "status",
            "shipmentPackageStatus",
            "cargoTrackingNumber",
            "cargoProviderName",
            "customerId",
            "lastModifiedDate",
            "price",
            "vatBaseAmount",
            "tyDiscount",
            "amount",
        ]

        # ✅ Model oluştur
        self.model = SQLModelTableModel(filtered_data, columns)

        # ✅ Proxy
        self.proxy_model = MultiFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)

        # ✅ Tablo
        self.table = QTableView()
        self.table.setModel(self.proxy_model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        # ✅ Filtre kutuları
        filter_box = QGroupBox("Filtreler")
        filter_layout = QHBoxLayout(filter_box)

        for col in range(len(columns)):
            input_field = QLineEdit()
            input_field.setPlaceholderText(columns[col])
            input_field.textChanged.connect(
                lambda text, c=col: self.proxy_model.setFilterForColumn(c, text)
            )
            filter_layout.addWidget(input_field)

        layout.insertWidget(0, filter_box)







class OrdersTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # 🟡 Üst bilgilendirme yazısı
        self.info_label = QLabel("Siparişleri buradan yönetebilirsin.")
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
    def on_orders_fetched(self):
        self.info_label.setText("✅ Siparişler başarıyla alındı.")
        self.orders_window = OrdersListWindow()
        self.orders_window.show()

    def update_progress(self, current, total):
        percent = int(current / total * 100)
        self.fetch_button.setProgress(percent)
