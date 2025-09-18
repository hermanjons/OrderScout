from Feedback.processors.pipeline import map_error_to_message
from Feedback.processors.pipeline import Result
import datetime
from Core.utils.model_utils import create_records
from Account.models import ApiAccount
from PyQt6.QtGui import QIcon, QAction, QPixmap
from PyQt6.QtCore import Qt
import os
from settings import MEDIA_ROOT  # icon dosyası burada
import shutil


def handle_company_save(dialog_instance):
    try:
        form_values = {
            "account_id": dialog_instance.seller_id_input.text(),
            "comp_name": dialog_instance.comp_name_input.text(),
            "api_key": dialog_instance.api_key_input.text(),
            "api_secret": dialog_instance.api_secret_input.text(),
            "platform": dialog_instance.platform_input.currentText(),
            "logo_path": dialog_instance.logo_path,
            "created_at": datetime.datetime.utcnow(),
        }

        create_records(
            model=ApiAccount,
            mode="plain",
            data_list=[form_values],
            db_name="orders.db",
            conflict_keys=["account_id", "comp_name", "platform"]
        )

        return Result.ok("Şirket başarıyla kaydedildi.")
    except Exception as e:

        user_message = map_error_to_message(e)
        return Result.fail(user_message, error=e)



def process_logo(file_path: str, max_size: int = 256) -> tuple[str, QPixmap]:
    """
    Seçilen logo dosyasını company_logos klasörüne kopyalar,
    gerekirse küçültür ve (save_path, pixmap) döner.
    """
    if not file_path:
        return None, None

    pixmap = QPixmap(file_path)
    if pixmap.width() > max_size or pixmap.height() > max_size:
        pixmap = pixmap.scaled(max_size, max_size, Qt.AspectRatioMode.KeepAspectRatio)

    logos_dir = os.path.join(MEDIA_ROOT, "company_logos")
    os.makedirs(logos_dir, exist_ok=True)
    file_name = os.path.basename(file_path)
    save_path = os.path.join(logos_dir, file_name)
    shutil.copy(file_path, save_path)

    return save_path, pixmap