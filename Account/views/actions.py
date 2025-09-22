from Account.constants.constants import PLATFORMS
from Feedback.processors.pipeline import Result, MessageHandler, map_error_to_message
import datetime
from Account.processors.pipeline import (
    save_company_to_db,
    process_logo,
    get_all_companies,
    get_company_by_id,
    update_company,
    delete_company_from_db,
)
import json
import os
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem

from typing import Optional, Tuple


# ==========================================================
# 📌 Tablo İşlemleri
# ==========================================================
def build_company_table(table_widget) -> Result:
    """
    DB’den şirketleri çeker ve tabloya doldurur.
    """
    try:
        res = get_all_companies()
        if not res.success:
            return res

        # ✅ Yeni Result.data kullanımı
        records = res.data.get("records", [])

        table_widget.setRowCount(0)

        for row, acc in enumerate(records):
            table_widget.insertRow(row)

            item_logo = QTableWidgetItem()
            if acc.logo_path and os.path.exists(acc.logo_path):
                item_logo.setIcon(QIcon(acc.logo_path))

            # pk'yi gizli sakla
            item_logo.setData(Qt.ItemDataRole.UserRole, acc.pk)

            columns = [
                item_logo,
                QTableWidgetItem(acc.comp_name or ""),
                QTableWidgetItem(acc.account_id or ""),
                QTableWidgetItem(acc.platform or ""),
                QTableWidgetItem("Aktif" if acc.is_active else "Pasif"),
            ]
            for col, item in enumerate(columns):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table_widget.setItem(row, col, item)

            table_widget.setRowHeight(row, 40)

        return Result.ok("Şirketler başarıyla yüklendi.", close_dialog=False)

    except Exception as e:
        msg = map_error_to_message(e)
        return Result.fail(msg, error=e)


def refresh_table(table, msg: str = "Tablo güncellendi.") -> Result:
    result = build_company_table(table)
    if not result.success:
        return result
    return Result.ok(msg, close_dialog=False)


# ==========================================================
# 📌 Form Doldurma ve Validasyon
# ==========================================================
def fill_company_form(dialog_instance, account) -> Result:
    """
    Verilen ApiAccount objesindeki değerleri CompanyFormDialog formuna basar.
    """
    try:
        dialog_instance.seller_id_input.setText(account.account_id or "")
        dialog_instance.comp_name_input.setText(account.comp_name or "")
        dialog_instance.api_key_input.setText(account.api_key or "")
        dialog_instance.api_secret_input.setText(account.api_secret or "")
        dialog_instance.integration_code_input.setText(account.integration_code or "")
        dialog_instance.token_input.setText(account.token or "")

        # Platform
        items = [dialog_instance.platform_input.itemText(i)
                 for i in range(dialog_instance.platform_input.count())]
        if getattr(account, "platform", None) in items:
            dialog_instance.platform_input.setCurrentText(account.platform)

        # Extra Config
        extra = getattr(account, "extra_config", None)
        try:
            if isinstance(extra, dict):
                dialog_instance.extra_config_input.setPlainText(
                    json.dumps(extra, indent=2, ensure_ascii=False)
                )
            elif isinstance(extra, str):
                try:
                    parsed = json.loads(extra)
                except Exception:
                    dialog_instance.extra_config_input.setPlainText(extra)
                else:
                    dialog_instance.extra_config_input.setPlainText(
                        json.dumps(parsed, indent=2, ensure_ascii=False)
                    )
            else:
                dialog_instance.extra_config_input.setPlainText("")
        except Exception:
            dialog_instance.extra_config_input.setPlainText("")

        dialog_instance.is_active_input.setChecked(bool(getattr(account, "is_active", False)))

        logo_path = getattr(account, "logo_path", None)
        if logo_path and os.path.exists(logo_path):
            pm = QPixmap(logo_path)
            if not pm.isNull():
                pm = pm.scaled(
                    dialog_instance.logo_preview.width(),
                    dialog_instance.logo_preview.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                dialog_instance.logo_preview.setPixmap(pm)
                dialog_instance.logo_path = logo_path
            else:
                dialog_instance.logo_preview.clear()
                dialog_instance.logo_path = None
        else:
            dialog_instance.logo_preview.clear()
            dialog_instance.logo_path = None

        return Result.ok("Form dolduruldu.", close_dialog=False)

    except Exception as e:
        msg = map_error_to_message(e)
        return Result.fail(msg, error=e, close_dialog=False)


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


def collect_form_values(dialog_instance) -> Tuple[Optional[dict], Result]:
    try:
        values = {
            "account_id": dialog_instance.seller_id_input.text().strip(),
            "comp_name": dialog_instance.comp_name_input.text().strip(),
            "api_key": dialog_instance.api_key_input.text().strip(),
            "api_secret": dialog_instance.api_secret_input.text().strip(),
            "integration_code": dialog_instance.integration_code_input.text().strip(),
            "token": dialog_instance.token_input.text().strip(),
            "platform": dialog_instance.platform_input.currentText(),
            "logo_path": dialog_instance.logo_path,
            "is_active": dialog_instance.is_active_input.isChecked(),
        }

        try:
            text = dialog_instance.extra_config_input.toPlainText().strip()
            values["extra_config"] = json.loads(text) if text else None
        except Exception as e:
            return None, Result.fail("Extra Config JSON formatı geçersiz.", error=e)

        validation = validate_form_values(values)
        if not validation.success:
            return None, validation

        return values, validation

    except Exception as e:
        msg = map_error_to_message(e)
        return None, Result.fail(msg, error=e)


# ==========================================================
# 📌 Form Kaydetme / Logo Yükleme
# ==========================================================
def handle_company_submit(dialog_instance) -> Result:
    values, validation = collect_form_values(dialog_instance)
    if not values:
        return validation

    if dialog_instance.account is None:
        values["created_at"] = datetime.datetime.utcnow()
        return save_company_to_db(values)
    else:
        values["last_used_at"] = datetime.datetime.utcnow()
        res = update_company(dialog_instance.account.pk, values)
        return Result.ok("Şirket güncellendi.") if res.success else Result.fail("Şirket güncellenemedi!")


def handle_logo_selection(dialog_instance, file_path: str) -> Result:
    try:
        res = process_logo(file_path)
        if not res.success:
            return res

        # ✅ Yeni kullanım
        save_path = res.data["path"]
        dialog_instance.logo_path = save_path

        pixmap = QPixmap(save_path).scaled(
            dialog_instance.logo_preview.width(),
            dialog_instance.logo_preview.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        ok = Result.ok("Logo başarıyla yüklendi.", close_dialog=False, data={"pixmap": pixmap})
        return ok

    except Exception as e:
        msg = map_error_to_message(e)
        return Result.fail(msg, error=e, close_dialog=False)


# ==========================================================
# 📌 Silme İşlemi
# ==========================================================
def delete_company_and_refresh(table, pk: int) -> Result:
    try:
        res = delete_company_from_db(pk)
        if not res.success:
            return res

        refresh = build_company_table(table)
        if not refresh.success:
            return refresh

        return Result.ok("Şirket başarıyla silindi.", close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
