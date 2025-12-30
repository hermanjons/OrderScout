from PyQt6.QtWidgets import QMainWindow, QTabWidget, QToolBar
from PyQt6.QtGui import QIcon, QAction
import os

from settings import MEDIA_ROOT
from Orders.views.views import OrdersTab
from Account.views.views import CompanyManagerButton
from License.views import LicenseManagerButton  # ⬅️ yeni import


class MainInterface(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OrderScout - Ana Panel")
        self.setGeometry(100, 100, 1000, 700)

        main_icon = os.path.join(MEDIA_ROOT, "sniper_icon.ico")
        self.setWindowIcon(QIcon(main_icon))

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.init_toolbar()
        self.init_tabs()

    def init_toolbar(self):
        self.toolBar = QToolBar("Ana Toolbar")
        self.addToolBar(self.toolBar)

        # Şirket Yönetimi butonu
        self.company_ui = CompanyManagerButton(self)
        self.toolBar.addAction(self.company_ui.create_action())

        # Lisans Yönetimi butonu
        self.license_ui = LicenseManagerButton(self)
        self.toolBar.addAction(self.license_ui.create_action())

    def init_tabs(self):
        self.orders_tab = OrdersTab()
        self.tabs.addTab(self.orders_tab, "Siparişler")
