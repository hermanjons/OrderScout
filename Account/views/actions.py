# accounts/views/actions.py
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtCore import QSize
import os
from settings import MEDIA_ROOT  # icon dosyası burada
from Account.models import ApiAccount
from Core.utils.model_utils import create_records
import datetime
# accounts/views/actions.py







def save_company_data(dialog_instance, form_values: dict, db_name="orders.db"):
    """
    Dışarıdan gelen form verisini kaydeder, mesaj kutusu döner.
    """
    try:
        data = {
            "seller_id": int(form_values["seller_id"]),
            "comp_name": form_values["comp_name"],
            "api_key": form_values["api_key"],
            "api_secret": form_values["api_secret"],
            "platform": form_values["platform"],
            "created_at": datetime.datetime.utcnow(),
        }

        create_records(
            model=ApiAccount,
            data_list=[data],
            db_name=db_name,
            conflict_keys=["seller_id"]
        )

        QMessageBox.information(dialog_instance, "Başarılı", "Şirket başarıyla kaydedildi.")
        dialog_instance.accept()

    except Exception as e:
        QMessageBox.critical(dialog_instance, "Hata", f"Şirket kaydı başarısız oldu:\n{e}")




def get_company_register_action(parent=None):
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

    # ✅ Circular import'a engel olmak için burada import et
    def open_register_dialog():
        from Account.views.views import CompanyRegisterDialog
        dialog = CompanyRegisterDialog()
        dialog.exec()

    action.triggered.connect(open_register_dialog)
    return action