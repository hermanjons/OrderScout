from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QMessageBox, QComboBox, QLabel, QFileDialog,QVBoxLayout,QHBoxLayout,QTableWidget,
QTableWidgetItem
)

from PyQt6.QtGui import QIcon, QAction, QPixmap
from PyQt6.QtCore import QSize, Qt
from Account.views.actions import open_register_dialog, collect_form_and_save

from Account.processors.pipeline import save_company_to_db, process_logo
from Account.constants.constants import PLATFORMS
import os
from Feedback.processors.pipeline import MessageHandler
from settings import MEDIA_ROOT




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




class CompanyManagerDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Şirket Yönetimi")
        self.resize(800, 600)

        main_layout = QVBoxLayout()

        # ✅ Butonlar
        button_layout = QHBoxLayout()
        self.add_button = QPushButton("Yeni Şirket Ekle")
        self.edit_button = QPushButton("Düzenle")
        self.delete_button = QPushButton("Sil")
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)

        # ✅ Şirket Tablosu
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Logo", "Şirket Adı", "Satıcı ID", "Platform", "Durum"])
        self.table.setIconSize(QSize(32, 32))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        # ✅ Buton eventleri
        self.add_button.clicked.connect(self.add_company)
        self.edit_button.clicked.connect(self.edit_company)
        self.delete_button.clicked.connect(self.delete_company)

        # Layout birleştir
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.table)
        self.setLayout(main_layout)

        # 🔄 Başlangıçta tabloyu yükle
        self.load_companies()

    def load_companies(self):
        # Burada DB’den ApiAccount kayıtlarını çekip tabloya dolduracaksın
        self.table.setRowCount(0)
        records = self.get_all_accounts()
        for row, acc in enumerate(records):
            self.table.insertRow(row)

            # Logo
            if acc.logo_path and os.path.exists(acc.logo_path):
                icon = QIcon(acc.logo_path)
                item_logo = QTableWidgetItem()
                item_logo.setIcon(icon)
            else:
                item_logo = QTableWidgetItem("")

            self.table.setItem(row, 0, item_logo)
            self.table.setItem(row, 1, QTableWidgetItem(acc.comp_name))
            self.table.setItem(row, 2, QTableWidgetItem(acc.account_id))
            self.table.setItem(row, 3, QTableWidgetItem(acc.platform))
            self.table.setItem(row, 4, QTableWidgetItem("Aktif" if acc.is_active else "Pasif"))

    def get_all_accounts(self):
        # DB’den ApiAccount objelerini çek
        from Account.models import ApiAccount
        from sqlmodel import Session, select
        from Core.utils.model_utils import get_engine

        engine = get_engine("orders.db")
        with Session(engine) as session:
            return session.exec(select(ApiAccount)).all()

    def add_company(self):
        dialog = CompanyRegisterDialog()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_companies()

    def edit_company(self):
        row = self.table.currentRow()
        if row < 0:
            return
        comp_name = self.table.item(row, 1).text()
        # Burada seçili kayda göre CompanyRegisterDialog açılacak ve update yapılacak

    def delete_company(self):
        row = self.table.currentRow()
        if row < 0:
            return
        comp_name = self.table.item(row, 1).text()
        # Burada DB’den silme işlemi yapılacak
        self.load_companies()



