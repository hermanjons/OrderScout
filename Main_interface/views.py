from PyQt6.QtWidgets import QMainWindow, QTabWidget
from PyQt6.QtGui import QIcon
from Orders.views import OrdersTab
import os
from settings import MEDIA_ROOT


class MainInterface(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OrderScout - Ana Panel")
        self.setGeometry(100, 100, 1000, 700)

        main_icon = os.path.join(MEDIA_ROOT, "sniper_icon.ico")
        self.setWindowIcon(QIcon(main_icon))

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.init_tabs()

    def init_tabs(self):
        self.orders_tab = OrdersTab()
        self.tabs.addTab(self.orders_tab, "Siparişler")
