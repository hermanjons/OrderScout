from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QMessageBox, QComboBox, QLabel, QFileDialog
)

from PyQt6.QtGui import QIcon, QAction, QPixmap
from PyQt6.QtCore import QSize, Qt
from Account.views.actions import open_register_dialog

from Account.processors.pipeline import handle_company_save,process_logo
from Account.constants.constants import PLATFORMS
import os
from Feedback.processors.pipeline import MessageHandler
from settings import MEDIA_ROOT



class CompanyRegisterDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Şirket Kaydı")

        # 🔽 İkon
        icon_path = os.path.join(MEDIA_ROOT, "add_button.png")
        self.setWindowIcon(QIcon(icon_path))

        # 🔧 Form düzeni
        self.form_layout = QFormLayout()

        self.seller_id_input = QLineEdit()
        self.comp_name_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_secret_input = QLineEdit()

        # ✅ Platform seçimi
        self.platform_input = QComboBox()
        self.platform_input.addItems(PLATFORMS)
        self.platform_input.setCurrentText("TRENDYOL")

        # 🖼️ Logo seçimi
        self.logo_path = None
        self.logo_preview = QLabel("Logo seçilmedi")
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.logo_button = QPushButton("Logo Seç")
        self.logo_button.clicked.connect(self.select_logo)

        # 🔲 Form alanları
        self.form_layout.addRow("Satıcı ID:", self.seller_id_input)
        self.form_layout.addRow("Şirket Adı:", self.comp_name_input)
        self.form_layout.addRow("API Key:", self.api_key_input)
        self.form_layout.addRow("API Secret:", self.api_secret_input)
        self.form_layout.addRow("Platform:", self.platform_input)
        self.form_layout.addRow("Logo:", self.logo_button)
        self.form_layout.addRow(self.logo_preview)

        # ✅ Kaydet butonu
        self.submit_button = QPushButton("Kaydet")
        self.submit_button.clicked.connect(
            lambda: MessageHandler.show(self, handle_company_save(self))
        )


        self.form_layout.addWidget(self.submit_button)

        self.setLayout(self.form_layout)

    def select_logo(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Logo Seç", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            save_path, pixmap = process_logo(file_path)
            if save_path and pixmap:
                self.logo_preview.setPixmap(pixmap)
                self.logo_path = save_path
                print(self.logo_path)


def create_company_register_action(parent=None):
    icon_path = os.path.join(MEDIA_ROOT, "add_button.png")

    action = QAction(QIcon(icon_path), "Şirket Ekle", parent)
    action.setToolTip("Yeni şirket API hesabı ekle")
    action.setIconText("Şirket Ekle")
    action.setIconVisibleInMenu(True)
    action.setData("company_register")
    action.setEnabled(True)
    action.setCheckable(False)

    if parent and hasattr(parent, "toolBar"):
        parent.toolBar.setIconSize(QSize(32, 32))

    # 🔗 İş mantığını actions.py’den bağla
    action.triggered.connect(lambda: open_register_dialog(parent))
    return action
