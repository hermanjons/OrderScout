from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QMessageBox, QComboBox, QLabel, QFileDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget,
    QTableWidgetItem, QSizePolicy, QHeaderView, QPlainTextEdit, QListWidget
)

from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QSize, Qt
from Account.views.actions import handle_company_submit, fill_company_form, handle_logo_selection, \
    build_company_table

from Account.constants.constants import PLATFORMS
from Feedback.processors.pipeline import MessageHandler, Result
from settings import MEDIA_ROOT
from Core.views.views import SwitchButton
import os
from Account.signals.signals import account_signals


class CompanyManagerButton:
    """
    Toolbar üzerinde 'Şirket Yönetimi' butonunu temsil eder.
    """

    def __init__(self, parent=None):
        self.parent = parent

    def create_action(self):
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
        dlg = CompanyManagerDialog()
        dlg.exec()


class CompanyManagerDialog(QDialog):
    """
    Şirket yönetim ekranı.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Şirket Yönetimi")
        self.setMinimumSize(900, 600)
        self.setMaximumSize(1000, 700)

        main_layout = QVBoxLayout()

        # -------------------------------------------------
        # ✅ Üstteki Butonlar
        # -------------------------------------------------
        button_layout = QHBoxLayout()
        self.add_button = QPushButton("Yeni Şirket Ekle")
        self.edit_button = QPushButton("Düzenle")
        self.delete_button = QPushButton("Sil")

        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)

        self.edit_button.setEnabled(False)
        self.delete_button.setEnabled(False)

        # -------------------------------------------------
        # 🔽 Pencere İkonu
        # -------------------------------------------------
        icon_path = os.path.join(MEDIA_ROOT, "comp_ico.png")
        self.setWindowIcon(QIcon(icon_path))

        # -------------------------------------------------
        # ✅ Şirket Tablosu
        # -------------------------------------------------
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

        self.add_button.clicked.connect(self.add_company)
        self.edit_button.clicked.connect(self.edit_company)
        self.delete_button.clicked.connect(self.delete_company)

        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.table)
        self.setLayout(main_layout)

        result = build_company_table(self.table)
        MessageHandler.show(self, result, only_errors=True)

    # -------------------------------------------------
    # 📌 Yeni Şirket Ekleme
    # -------------------------------------------------
    def add_company(self):
        dialog = CompanyFormDialog()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = build_company_table(self.table)
            MessageHandler.show(self, result, only_errors=True)

    # -------------------------------------------------
    # 📌 Şirket Düzenleme
    # -------------------------------------------------
    def edit_company(self):
        row = self.table.currentRow()
        if row < 0:
            return

        pk = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

        from Account.processors.pipeline import get_company_by_id
        res = get_company_by_id([pk])  # parametre zaten list[int] olmalı
        if not res.success:
            MessageHandler.show(self, res, only_errors=True)
            return

        records = res.data["records"]
        if not records:
            return  # ya da Result.fail dön

        acc = records[0]  # ✅ tek kaydı al
        dialog = CompanyFormDialog(account=acc, parent=self)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            refresh = build_company_table(self.table)
            MessageHandler.show(self, refresh, only_errors=True)

    # -------------------------------------------------
    # 📌 Şirket Silme
    # -------------------------------------------------
    def delete_company(self):
        row = self.table.currentRow()
        if row < 0:
            res = Result.fail("Herhangi bir şirket seçilmedi.", close_dialog=False)
            MessageHandler.show(self, res, only_errors=True)
            return

        pk_item = self.table.item(row, 0)
        name_item = self.table.item(row, 1)

        if pk_item is None or name_item is None:
            res = Result.fail("Seçim okunamadı.", close_dialog=False)
            MessageHandler.show(self, res, only_errors=True)
            return

        pk = pk_item.data(Qt.ItemDataRole.UserRole)
        comp_name = name_item.text()

        confirm = QMessageBox.question(
            self,
            "Silme Onayı",
            f"{comp_name} şirketini silmek istediğine emin misin?"
        )

        if confirm == QMessageBox.StandardButton.Yes:
            from Account.views.actions import delete_company_and_refresh
            result = delete_company_and_refresh(self.table, pk)
            MessageHandler.show(self, result)

    def update_button_states(self):
        has_selection = len(self.table.selectionModel().selectedRows()) > 0
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)


class CompanyFormDialog(QDialog):
    """
    Şirket ekleme ve düzenleme için kullanılan form dialogu.
    """

    def __init__(self, account=None, parent=None):
        super().__init__(parent)
        self.account = account
        self.setWindowTitle("Şirket Kaydı" if account is None else "Şirket Düzenle")

        icon_path = os.path.join(MEDIA_ROOT, "add_button.png")
        self.setWindowIcon(QIcon(icon_path))

        self.form_layout = QFormLayout()

        self.seller_id_input = QLineEdit()
        self.comp_name_input = QLineEdit()

        self.api_key_input = QLineEdit()
        self.api_secret_input = QLineEdit()
        self.integration_code_input = QLineEdit()
        self.token_input = QLineEdit()

        self.platform_input = QComboBox()
        self.platform_input.addItems(PLATFORMS)
        self.platform_input.setCurrentText("TRENDYOL")

        self.extra_config_input = QPlainTextEdit()
        self.extra_config_input.setPlaceholderText('{"region": "EU", "merchant_id": "123"}')

        self.is_active_input = SwitchButton()
        self.is_active_input.setChecked(True)

        self.logo_path = None
        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(360, 220)
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_preview.setStyleSheet("border: 1px solid #ccc; background: #fafafa;")

        self.logo_button = QPushButton("Logo Seç")
        self.logo_button.clicked.connect(self.select_logo)

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

        self.submit_button = QPushButton("Kaydet")
        self.submit_button.clicked.connect(self.on_submit)
        self.form_layout.addWidget(self.submit_button)

        self.setLayout(self.form_layout)
        self.setFixedSize(400, 700)

        if account is not None:
            print("hesap:", account)
            res = fill_company_form(self, account)
            if not res.success:
                MessageHandler.show(self, res, only_errors=True)

    def select_logo(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Logo Seç", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            res = handle_logo_selection(self, file_path)
            MessageHandler.show(self, res, only_errors=True)
            if res.success:
                # ✅ Yeni Result.data kullanımı
                self.logo_preview.setPixmap(res.data["pixmap"])

    def on_submit(self):
        result = handle_company_submit(self)
        MessageHandler.show(self, result)
        if result.success:
            self.accept()


class CompanyListWidget(QListWidget):
    """
    SwitchButton ile şirket seçimi yapılabilen liste widget.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        account_signals.company_changed.connect(self.build_from_db)

    def build_from_db(self):
        """
        DB’den şirketleri çekip listeyi doldurur.
        """
        from Account.processors.pipeline import get_all_companies
        from Account.views.actions import build_company_list

        result = get_all_companies()
        if not result.success:
            return result

        # records çıkarmak yerine Result'u direkt gönder
        return build_company_list(self, result)
