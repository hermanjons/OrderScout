from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from Orders.processors.pipeline import fetch_orders_all
from Core.constants.request_constants import status_list
from PyQt6.QtCore import QThread, pyqtSignal
import asyncio

start_ep_time = 1752073397000
final_ep_time = 1751900597000

comp_api_account_list = (["MCN8sNGNPfCs18KwzzvT", "z1XHEgSvr9qRUo018y31", "784195"],)


class OrdersWorker(QThread):
    finished = pyqtSignal(list, list)

    def __init__(self, status_list, final_ep_time, start_ep_time, comp_api_account_list, parent=None):
        super().__init__(parent)
        self.status_list = status_list
        self.final_ep_time = final_ep_time
        self.start_ep_time = start_ep_time
        self.comp_api_account_list = comp_api_account_list

    def run(self):
        try:

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            orders, items = loop.run_until_complete(
                fetch_orders_all(self.status_list, self.final_ep_time, self.start_ep_time, self.comp_api_account_list)
            )
            self.finished.emit(orders, items)
        except Exception as e:
            print(e)


class OrdersTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        self.info_label = QLabel("Siparişleri buradan yönetebilirsin.")
        layout.addWidget(self.info_label)

        self.fetch_button = QPushButton("Siparişleri Getir")
        self.fetch_button.clicked.connect(self.get_orders)
        layout.addWidget(self.fetch_button)

        self.setLayout(layout)

    def get_orders(self):
        try:

            self.worker = OrdersWorker(status_list, final_ep_time, start_ep_time, comp_api_account_list)
            self.worker.finished.connect(self.on_orders_fetched)
            self.worker.start()
        except Exception as e:
            print(e)

    def on_orders_fetched(self, orders, items):
        print(f"{len(orders)} sipariş, {len(items)} ürün çekildi.")
        self.info_label.setText("Siparişler alındı.")
