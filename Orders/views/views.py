from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout, QListWidget
from PyQt6.QtCore import Qt
from Core.views.views import CircularProgressButton
from Orders.views.actions import fetch_with_worker

class OrdersTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # --- ÜST: bilgi metni ---
        self.info_label = QLabel("Siparişleri buradan yönetebilirsin.")
        layout.addWidget(self.info_label)

        # --- ALT: Bottom Panel (GroupBox) ---
        self.fetch_button = CircularProgressButton("BAŞLAT")
        self.fetch_button.clicked.connect(self.get_orders)

        self.bottom_panel = QGroupBox("Veri Çekme Paneli")
        self.bottom_panel.setFixedHeight(160)
        bottom_layout = QHBoxLayout()
        self.bottom_panel.setLayout(bottom_layout)

        # Sol: Şirket listesi (görsel liste)
        self.company_list = QListWidget()
        self.company_list.setFixedWidth(180)
        self.company_list.addItems(["dene","dene2","mdb"])  # burayı DB'den çek
        bottom_layout.addWidget(self.company_list)

        # Orta: Buton ortalı
        btn_container = QWidget()
        btn_layout = QVBoxLayout(btn_container)
        btn_layout.addStretch()
        btn_layout.addWidget(self.fetch_button, alignment=Qt.AlignmentFlag.AlignCenter)
        btn_layout.addStretch()

        bottom_layout.addWidget(btn_container)

        layout.addWidget(self.bottom_panel)

    def get_orders(self):
        try:
            fetch_with_worker(self)
        except Exception as e:
            print(e)

    def on_orders_fetched(self):
        self.info_label.setText("Siparişler alındı.")
