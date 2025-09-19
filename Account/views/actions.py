from Account.constants.constants import PLATFORMS
from Feedback.processors.pipeline import Result
import datetime
from Account.processors.pipeline import save_company_to_db


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
    dlg = CompanyManagerDialog()     # ← örnekle
    dlg.exec()                             # ← modal aç
