from Account.constants.constants import PLATFORMS
from Feedback.processors.pipeline import Result
import datetime
from Account.processors.pipeline import save_company_to_db, process_logo, get_all_companies
import json
import os
from PyQt6.QtGui import QPixmap,QIcon
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidget,QTableWidgetItem





def build_company_table(table_widget):
    """DB’den şirketleri çeker ve verilen tabloya doldurur"""
    records = get_all_companies()
    table_widget.setRowCount(0)

    for row, acc in enumerate(records):
        table_widget.insertRow(row)

        # Logo
        if acc.logo_path and os.path.exists(acc.logo_path):
            icon = QIcon(acc.logo_path)
            item_logo = QTableWidgetItem()
            item_logo.setIcon(icon)
        else:
            item_logo = QTableWidgetItem("")

        # Read-only hücreler
        columns = [
            item_logo,
            QTableWidgetItem(acc.comp_name),
            QTableWidgetItem(acc.account_id),
            QTableWidgetItem(acc.platform),
            QTableWidgetItem("Aktif" if acc.is_active else "Pasif"),
        ]
        for col, item in enumerate(columns):
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table_widget.setItem(row, col, item)
        table_widget.setRowHeight(row, 40)






def fill_company_form(dialog_instance, account):
    """
    Verilen ApiAccount objesindeki değerleri CompanyRegisterDialog formuna basar.
    """

    dialog_instance.seller_id_input.setText(account.account_id)
    dialog_instance.comp_name_input.setText(account.comp_name)
    dialog_instance.api_key_input.setText(account.api_key or "")
    dialog_instance.api_secret_input.setText(account.api_secret or "")
    dialog_instance.integration_code_input.setText(account.integration_code or "")
    dialog_instance.token_input.setText(account.token or "")
    dialog_instance.platform_input.setCurrentText(account.platform)
    dialog_instance.extra_config_input.setPlainText(json.dumps(account.extra_config or {}, indent=2))
    dialog_instance.is_active_input.setChecked(account.is_active)

    if account.logo_path and os.path.exists(account.logo_path):
        pixmap = QPixmap(account.logo_path).scaled(
            dialog_instance.logo_preview.width(),
            dialog_instance.logo_preview.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        dialog_instance.logo_preview.setPixmap(pixmap)
        dialog_instance.logo_path = account.logo_path


def validate_form_values(values: dict) -> Result:
    if not values.get("account_id"):
        return Result.fail("Satıcı ID boş bırakılamaz.")
    if not values.get("comp_name"):
        return Result.fail("Şirket adı boş bırakılamaz.")
    if not values.get("platform"):
        return Result.fail("Platform seçilmelidir.")
    if values["platform"] not in PLATFORMS:
        return Result.fail(f"Geçersiz platform: {values['platform']}")
    return Result.ok("Validasyon başarılı.")


def collect_form_and_save(dialog_instance):
    form_values = {
        "account_id": dialog_instance.seller_id_input.text(),
        "comp_name": dialog_instance.comp_name_input.text(),
        "api_key": dialog_instance.api_key_input.text(),
        "api_secret": dialog_instance.api_secret_input.text(),
        "platform": dialog_instance.platform_input.currentText(),
        "logo_path": dialog_instance.logo_path,
        "created_at": datetime.datetime.utcnow(),
    }

    # ✅ Önce validation
    validation = validate_form_values(form_values)
    if not validation.success:
        return validation

    # ✅ Pipeline'a gönder
    return save_company_to_db(form_values)


def open_register_dialog(parent=None):
    from Account.views.views import CompanyManagerDialog
    dlg = CompanyManagerDialog()  # ← örnekle
    dlg.exec()  # ← modal aç


def handle_logo_selection(dialog_instance, file_path: str):
    """
    Pipeline ile dosyayı kopyalar, UI için pixmap hazırlar.
    Hem path'i dialog_instance.logo_path'e yazar hem pixmap döner.
    """
    save_path = process_logo(file_path)
    if save_path:
        dialog_instance.logo_path = save_path
        pixmap = QPixmap(save_path).scaled(
            dialog_instance.logo_preview.width(),
            dialog_instance.logo_preview.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        return pixmap
    return None