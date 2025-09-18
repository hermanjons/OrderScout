from PyQt6.QtWidgets import QMainWindow, QTabWidget, QToolBar
from PyQt6.QtGui import QIcon, QAction
from Orders.views.views import OrdersTab
from Account.views.views import CompanyRegisterDialog
import os
from settings import MEDIA_ROOT
from Account.views.views import create_company_register_action


class MainInterface(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OrderScout - Ana Panel")
        self.setGeometry(100, 100, 1000, 700)

        main_icon = os.path.join(MEDIA_ROOT, "sniper_icon.ico")
        self.setWindowIcon(QIcon(main_icon))

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.init_toolbar()  # ✅ Yeni toolbar
        self.init_tabs()

    def init_toolbar(self):
        self.toolBar = QToolBar("Ana Toolbar")
        self.addToolBar(self.toolBar)

        # Şirket kayıt aksiyonunu dışardan getiriyoruz (prensibe uygun!)
        company_action = create_company_register_action(self)
        self.toolBar.addAction(company_action)


    def init_tabs(self):
        self.orders_tab = OrdersTab()
        self.tabs.addTab(self.orders_tab, "Siparişler")
