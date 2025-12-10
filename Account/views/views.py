from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QMessageBox, QComboBox, QLabel, QFileDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget,
    QTableWidgetItem, QSizePolicy, QHeaderView, QPlainTextEdit, QListWidget,QFrame
)

from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QSize, Qt
from Account.views.actions import handle_company_submit, fill_company_form, handle_logo_selection, \
    build_company_table,build_company_list

from Account.constants.constants import PLATFORMS
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from settings import MEDIA_ROOT
from Core.views.views import SwitchButton
import os
from Account.signals.signals import account_signals
from Account.processors.pipeline import get_all_companies,get_active_companies


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

        # -------------------------------------------------
        # 🎨 Genel Stil
        # -------------------------------------------------
        self.setObjectName("CompanyDialogRoot")
        self.setStyleSheet("""
        QDialog#CompanyDialogRoot {
            background-color: #F3F4F6;
            color: #111827;
        }

        QFrame#HeaderCard {
            border-radius: 12px;
            border: none;
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #111827,
                stop:1 #020617
            );
        }
        QLabel#HeaderTitle {
            font-size: 15px;
            font-weight: 600;
            color: #F9FAFB;
        }
        QLabel#HeaderSubtitle {
            font-size: 11px;
            color: #E5E7EB;
        }

        QFrame#SectionCard {
            background-color: #FFFFFF;
            border-radius: 12px;
            border: 1px solid #E5E7EB;
        }
        QLabel#SectionTitle {
            font-size: 12px;
            font-weight: 600;
            color: #111827;
        }

        QPushButton#PrimaryButton {
            background-color: #2563EB;
            color: #FFFFFF;
            border-radius: 6px;
            padding: 6px 14px;
            border: none;
            font-weight: 500;
        }
        QPushButton#PrimaryButton:hover {
            background-color: #1D4ED8;
        }
        QPushButton#PrimaryButton:disabled {
            background-color: #9CA3AF;
            color: #E5E7EB;
        }

        QPushButton#SecondaryButton {
            background-color: #E5E7EB;
            color: #111827;
            border-radius: 6px;
            padding: 6px 14px;
            border: none;
            font-weight: 500;
        }
        QPushButton#SecondaryButton:hover {
            background-color: #D1D5DB;
        }
        QPushButton#SecondaryButton:disabled {
            background-color: #E5E7EB;
            color: #9CA3AF;
        }

        QPushButton#DangerButton {
            background-color: #DC2626;
            color: #FEF2F2;
            border-radius: 6px;
            padding: 6px 14px;
            border: none;
            font-weight: 500;
        }
        QPushButton#DangerButton:hover {
            background-color: #B91C1C;
        }
        QPushButton#DangerButton:disabled {
            background-color: #FECACA;
            color: #7F1D1D;
        }

        QTableWidget {
            background-color: #FFFFFF;
            border-radius: 8px;
            border: 1px solid #E5E7EB;
            gridline-color: #E5E7EB;
            selection-background-color: #DBEAFE;
            selection-color: #1F2937;
        }
        QHeaderView::section {
            background-color: #F9FAFB;
            border: 1px solid #E5E7EB;
            padding: 6px;
            font-weight: 600;
            font-size: 11px;
        }
        """)

        # -------------------------------------------------
        # 🔽 Pencere İkonu
        # -------------------------------------------------
        icon_path = os.path.join(MEDIA_ROOT, "comp_ico.png")
        self.setWindowIcon(QIcon(icon_path))

        # -------------------------------------------------
        # 📐 Ana Layout
        # -------------------------------------------------
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(10)

        # -------------------------------------------------
        # 🧊 Header Kart
        # -------------------------------------------------
        header_card = QFrame()
        header_card.setObjectName("HeaderCard")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(12)

        header_text_layout = QVBoxLayout()
        lbl_title = QLabel("Şirket Yönetimi")
        lbl_title.setObjectName("HeaderTitle")

        lbl_subtitle = QLabel(
            "Bağlı olduğun e-ticaret mağazalarının API bilgilerini ekle, düzenle ve yönet."
        )
        lbl_subtitle.setObjectName("HeaderSubtitle")
        lbl_subtitle.setWordWrap(True)

        header_text_layout.addWidget(lbl_title)
        header_text_layout.addWidget(lbl_subtitle)

        header_layout.addLayout(header_text_layout)
        header_layout.addStretch()

        main_layout.addWidget(header_card)

        # -------------------------------------------------
        # 📦 Ana Kart: Butonlar + Tablo
        # -------------------------------------------------
        section_card = QFrame()
        section_card.setObjectName("SectionCard")
        section_layout = QVBoxLayout(section_card)
        section_layout.setContentsMargins(14, 10, 14, 12)
        section_layout.setSpacing(8)

        # Üst satır: başlık + butonlar
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        lbl_section_title = QLabel("Kayıtlı Mağazalar")
        lbl_section_title.setObjectName("SectionTitle")

        top_row.addWidget(lbl_section_title)
        top_row.addStretch()

        # ✅ Üstteki Butonlar
        self.add_button = QPushButton("Yeni Şirket Ekle")
        self.edit_button = QPushButton("Düzenle")
        self.delete_button = QPushButton("Sil")

        self.add_button.setObjectName("PrimaryButton")
        self.edit_button.setObjectName("SecondaryButton")
        self.delete_button.setObjectName("DangerButton")

        top_row.addWidget(self.add_button)
        top_row.addWidget(self.edit_button)
        top_row.addWidget(self.delete_button)

        section_layout.addLayout(top_row)

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

        section_layout.addWidget(self.table)

        main_layout.addWidget(section_card)

        # -------------------------------------------------
        # 🔗 Buton durumları ve sinyaller
        # -------------------------------------------------
        self.edit_button.setEnabled(False)
        self.delete_button.setEnabled(False)

        # seçim değişince butonları güncelle
        self.table.selectionModel().selectionChanged.connect(self.update_button_states)

        self.add_button.clicked.connect(self.add_company)
        self.edit_button.clicked.connect(self.edit_company)
        self.delete_button.clicked.connect(self.delete_company)

        # -------------------------------------------------
        # 🧱 Tabloyu doldur
        # -------------------------------------------------
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

    # -------------------------------------------------
    # 🔁 Buton aktif/pasif durumları
    # -------------------------------------------------
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
    SwitchButton ile şirket seçimi yapılabilen, kendine yeten liste widget'ı.
    - İlk gösterimde kendini yükler
    - Sinyal ile (company_changed) yeniden yükler
    - Render’ı actions.build_company_list ile yapar
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        # 🔌 Şirketler değiştiğinde otomatik yenile
        account_signals.company_changed.connect(self.reload_companies)

    # ============================================================
    # 🔄 Yaşam döngüsü
    # ============================================================
    def showEvent(self, event):
        """Widget ilk gösterildiğinde şirketleri yükle."""
        super().showEvent(event)
        if self.count() == 0:  # sadece ilk kez
            self.reload_companies()

    # ============================================================
    # 🧩 Ana işlemler
    # ============================================================
    def reload_companies(self):
        """
        DB’den şirketleri çekip listeyi yeniden kurar.
        """
        try:
            result = get_active_companies()
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                return

            self._safe_build(result)

        except Exception as e:
            msg = map_error_to_message(e)
            MessageHandler.show(self, Result.fail(msg, error=e), only_errors=True)

    # ============================================================
    # 🧰 Yardımcı işlemler
    # ============================================================
    def _safe_build(self, result: Result):
        """
        build_company_list çağrısını Qt leak koruması ile güvenli yap.
        """
        try:
            # 🧽 Qt memory leak koruması (mevcut widgetları öldür)
            for i in range(self.count()):
                w = self.itemWidget(self.item(i))
                if w:
                    w.deleteLater()
            self.clear()

            # 🏗️ actions.build_company_list Result objesiyle çalışıyor
            res = build_company_list(self, result)
            if not res.success:
                # Boş listeyi success kabul ettiği için genelde burası error’dur
                MessageHandler.show(self, res, only_errors=True)

        except Exception as e:
            MessageHandler.show(self, Result.fail(map_error_to_message(e), error=e), only_errors=True)

    # ============================================================
    # 📦 Seçim yardımcıları (opsiyonel, kullanmak istersen var)
    # ============================================================
    def get_selected_company_pks(self) -> list[int]:
        """
        ListSmartItemWidget içindeki switch’lere bakarak seçili şirket PK’larını döndür.
        (collect_selected_companies kullanmak istemeyen yerler için)
        """
        selected = []
        for i in range(self.count()):
            item = self.item(i)
            w = self.itemWidget(item)
            if not w:
                continue
            btn = getattr(w, "right_widget", None)
            if btn and btn.isChecked():
                # PK, build_company_list içinde UserRole olarak item’a set ediliyor
                pk = item.data(Qt.ItemDataRole.UserRole)
                if pk is not None:
                    selected.append(pk)
        return selected

    def select_all(self):
        """Listedeki tüm şirketleri seç."""
        for i in range(self.count()):
            w = self.itemWidget(self.item(i))
            if w and hasattr(w, "right_widget") and not w.right_widget.isChecked():
                w.right_widget.setChecked(True)

    def deselect_all(self):
        """Listedeki tüm seçimleri kaldır."""
        for i in range(self.count()):
            w = self.itemWidget(self.item(i))
            if w and hasattr(w, "right_widget") and w.right_widget.isChecked():
                w.right_widget.setChecked(False)
