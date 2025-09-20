from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QMessageBox, QComboBox, QLabel, QFileDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget,
    QTableWidgetItem, QSizePolicy,QHeaderView,QPlainTextEdit,QCheckBox
)

from PyQt6.QtGui import QIcon, QAction, QPixmap
from PyQt6.QtCore import QSize, Qt
from Account.views.actions import open_register_dialog, collect_form_and_save, fill_company_form, handle_logo_selection,\
    build_company_table

from Account.processors.pipeline import save_company_to_db, process_logo
from Account.constants.constants import PLATFORMS
import os
from Feedback.processors.pipeline import MessageHandler
from settings import MEDIA_ROOT
from Core.views.views import SwitchButton



class CompanyManagerButton:
    """Şirket yönetimi için toolbar action ve dialog açma işlevlerini kapsar."""

    def __init__(self, parent=None):
        self.parent = parent


    def create_action(self):
        """Toolbar'a eklenecek QAction'ı döndürür"""
        icon_path = os.path.join(MEDIA_ROOT, "comp_ico.png")
        action = QAction(QIcon(icon_path), "Şirket Yönetimi", self.parent)
        action.setToolTip("Şirket API hesaplarını yönet")
        action.setIconText("Şirket Yönetimi")
        action.setIconVisibleInMenu(True)
        action.setData("company_manager")
        action.setEnabled(True)
        action.setCheckable(False)

        if self.parent and hasattr(self.parent, "toolBar"):
            self.parent.toolBar.setIconSize(QSize(32, 32))

        action.triggered.connect(self.open_comp_manage_dialog)
        return action

    def open_comp_manage_dialog(self):
        """Şirket yönetim penceresini açar"""
        dlg = CompanyManagerDialog()
        dlg.exec()




class CompanyManagerDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Şirket Yönetimi")
        self.setMinimumSize(900, 600)
        self.setMaximumSize(1000, 700)

        main_layout = QVBoxLayout()

        # ✅ Butonlar
        button_layout = QHBoxLayout()
        self.add_button = QPushButton("Yeni Şirket Ekle")
        self.edit_button = QPushButton("Düzenle")
        self.delete_button = QPushButton("Sil")
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)
        # Başlangıçta kapalı
        self.edit_button.setEnabled(False)
        self.delete_button.setEnabled(False)

        # Satır seçimi değiştiğinde kontrol et

        # 🔽 İkon
        icon_path = os.path.join(MEDIA_ROOT, "comp_ico.png")
        self.setWindowIcon(QIcon(icon_path))

        # ✅ Şirket Tablosu
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Logo", "Şirket Adı", "Satıcı ID", "Platform", "Durum"])
        self.table.setIconSize(QSize(32, 32))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().selectionChanged.connect(self.update_button_states)
        self.edit_button.setStyleSheet("""
            QPushButton:disabled {
                background-color: #dcdcdc;
                color: #808080;
            }
        """)

        self.delete_button.setStyleSheet("""
            QPushButton:disabled {
                background-color: #dcdcdc;
                color: #808080;
            }
        """)

        # ✅ Buton eventleri
        self.add_button.clicked.connect(self.add_company)
        self.edit_button.clicked.connect(self.edit_company)
        self.delete_button.clicked.connect(self.delete_company)

        # Layout birleştir
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.table)
        self.setLayout(main_layout)

        # 🔄 Başlangıçta tabloyu yükle
        build_company_table(self.table)


    def add_company(self):
        from Account.views.views import CompanyRegisterDialog
        dialog = CompanyRegisterDialog()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            build_company_table(self.table)

    def edit_company(self):
        row = self.table.currentRow()
        if row < 0:
            return

        comp_name = self.table.item(row, 1).text()
        from Account.models import ApiAccount
        from sqlmodel import Session, select
        from Core.utils.model_utils import get_engine

        engine = get_engine("orders.db")
        with Session(engine) as session:
            acc = session.exec(select(ApiAccount).where(ApiAccount.comp_name == comp_name)).first()

        if not acc:
            QMessageBox.warning(self, "Hata", "Seçili şirket bulunamadı.")
            return

        # Düzenleme penceresi aç
        dialog = CompanyRegisterDialog(account=acc)
        dialog.seller_id_input.setText(acc.account_id)
        dialog.comp_name_input.setText(acc.comp_name)
        dialog.api_key_input.setText(acc.api_key or "")
        dialog.api_secret_input.setText(acc.api_secret or "")
        dialog.platform_input.setCurrentText(acc.platform)
        dialog.logo_path = acc.logo_path

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # TODO: DB update yapılacak
            build_company_table(self.table)

    def delete_company(self):
        row = self.table.currentRow()
        if row < 0:
            return

        comp_name = self.table.item(row, 1).text()
        confirm = QMessageBox.question(
            self, "Silme Onayı", f"{comp_name} şirketini silmek istediğine emin misin?"
        )
        if confirm == QMessageBox.StandardButton.Yes:
            from Account.models import ApiAccount
            from sqlmodel import Session, select
            from Core.utils.model_utils import get_engine

            engine = get_engine("orders.db")
            with Session(engine) as session:
                acc = session.exec(select(ApiAccount).where(ApiAccount.comp_name == comp_name)).first()
                if acc:
                    session.delete(acc)
                    session.commit()
            self.load_companies()

    def update_button_states(self):
        has_selection = len(self.table.selectionModel().selectedRows()) > 0
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)




class CompanyRegisterDialog(QDialog):
    def __init__(self, account=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Şirket Kaydı" if account is None else "Şirket Düzenle")

        # 🔽 İkon
        icon_path = os.path.join(MEDIA_ROOT, "add_button.png")
        self.setWindowIcon(QIcon(icon_path))

        # 🔧 Form düzeni
        self.form_layout = QFormLayout()

        # TEMEL
        self.seller_id_input = QLineEdit()
        self.comp_name_input = QLineEdit()

        # API Kimlik
        self.api_key_input = QLineEdit()
        self.api_secret_input = QLineEdit()
        self.integration_code_input = QLineEdit()
        self.token_input = QLineEdit()

        # Platform
        self.platform_input = QComboBox()
        self.platform_input.addItems(PLATFORMS)
        self.platform_input.setCurrentText("TRENDYOL")

        # Extra Config (JSON string)
        self.extra_config_input = QPlainTextEdit()
        self.extra_config_input.setPlaceholderText('{"region": "EU", "merchant_id": "123"}')

        # Aktif / Pasif (bizim toggle)
        self.is_active_input = SwitchButton()
        self.is_active_input.setChecked(True)  # varsayılan aktif

        # 🖼️ Logo önizleme alanı (sabit boyutlu)
        self.logo_path = None
        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(360, 220)  # pencerenin altını dolduracak
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_preview.setStyleSheet("border: 1px solid #ccc; background: #fafafa;")

        self.logo_button = QPushButton("Logo Seç")
        self.logo_button.clicked.connect(self.select_logo)

        # 🔲 Form alanları
        self.form_layout.addRow("Satıcı ID:", self.seller_id_input)
        self.form_layout.addRow("Şirket Adı:", self.comp_name_input)
        self.form_layout.addRow("API Key:", self.api_key_input)
        self.form_layout.addRow("API Secret:", self.api_secret_input)
        self.form_layout.addRow("Integration Code:", self.integration_code_input)
        self.form_layout.addRow("Token:", self.token_input)
        self.form_layout.addRow("Platform:", self.platform_input)
        self.form_layout.addRow("Extra Config (JSON):", self.extra_config_input)
        self.form_layout.addRow("Durum:", self.is_active_input)
        self.form_layout.addRow("Logo:", self.logo_button)
        self.form_layout.addRow(self.logo_preview)

        # ✅ Kaydet butonu
        self.submit_button = QPushButton("Kaydet")
        self.submit_button.clicked.connect(self.on_submit)
        self.form_layout.addWidget(self.submit_button)

        self.setLayout(self.form_layout)

        # 📏 Pencere sabit boyut
        self.setFixedSize(400, 700)

        # 🔄 Eğer düzenleme modundaysa formu doldur
        if account is not None:
            fill_company_form(self, account)

    def select_logo(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Logo Seç", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            pixmap = handle_logo_selection(self, file_path)
            if pixmap:
                self.logo_preview.setPixmap(pixmap)

    def on_submit(self):
        result = collect_form_and_save(self)
        MessageHandler.show(self, result)
        if result.success:
            self.accept()