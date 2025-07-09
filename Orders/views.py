from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel


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
        print("Siparişler çekiliyor...")
        self.info_label.setText("Siparişler başarıyla çekildi!")
