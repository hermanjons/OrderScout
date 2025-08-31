# accounts/views/views.py

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QToolBar, QDialog, QLineEdit, QFormLayout, \
    QMessageBox
from PyQt6.QtGui import QIcon
from Account.models import ApiAccount  # Modelin doğru import edildiğinden emin ol
from Core.utils.model_utils import create_records  # Kayıt eklemek için
import datetime
import os
from settings import MEDIA_ROOT
from Account.views.actions import save_company_data


class CompanyRegisterDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Şirket Kaydı")

        icon_path = os.path.join(MEDIA_ROOT, "add_button.png")
        self.setWindowIcon(QIcon(icon_path))

        self.form_layout = QFormLayout()

        self.seller_id_input = QLineEdit()
        self.comp_name_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_secret_input = QLineEdit()
        self.platform_input = QLineEdit()
        self.platform_input.setText("trendyol")

        self.form_layout.addRow("Satıcı ID:", self.seller_id_input)
        self.form_layout.addRow("Şirket Adı:", self.comp_name_input)
        self.form_layout.addRow("API Key:", self.api_key_input)
        self.form_layout.addRow("API Secret:", self.api_secret_input)
        self.form_layout.addRow("Platform:", self.platform_input)

        self.submit_button = QPushButton("Kaydet")
        self.submit_button.clicked.connect(self.save_company)

        self.form_layout.addWidget(self.submit_button)
        self.setLayout(self.form_layout)

    def save_company(self):
        form_values = {
            "seller_id": self.seller_id_input.text(),
            "comp_name": self.comp_name_input.text(),
            "api_key": self.api_key_input.text(),
            "api_secret": self.api_secret_input.text(),
            "platform": self.platform_input.text()
        }

        save_company_data(self, form_values)
