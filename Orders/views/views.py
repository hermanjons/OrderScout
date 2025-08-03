from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from Orders.processors.pipeline import fetch_orders_all
from Orders.constants.constants import status_list
import asyncio
from Core.threads.async_worker import AsyncWorker
from Orders.views.actions import fetch_with_worker


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
            fetch_with_worker(self)
        except Exception as e:
            print(e)

    def on_orders_fetched(self):
        self.info_label.setText("Siparişler alındı.")
