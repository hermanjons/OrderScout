from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
    QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt
from Core.views.views import CircularProgressButton, SwitchButton, ListSmartItemWidget
from Orders.views.actions import fetch_with_worker, populate_company_list, get_company_names_from_db, \
    get_api_credentials_by_names



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

    def update_progress(self, current, total):
        percent = int(current / total * 100)
        self.fetch_button.setProgress(percent)
