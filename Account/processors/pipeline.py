# Account/processors/pipeline.py
import datetime
import os, shutil
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt
from settings import MEDIA_ROOT
from Account.models import ApiAccount
from Core.utils.model_utils import create_records, make_normalizer
from Feedback.processors.pipeline import Result, map_error_to_message



account_normalizer = make_normalizer(
    coalesce_none={
        "account_id": None,
        "comp_name": None,
        "platform": None,
    },
    strip_strings=True
)


def save_company_to_db(form_values: dict) -> Result:
    try:
        create_records(
            model=ApiAccount,
            mode="plain",
            data_list=[form_values],
            db_name="orders.db",
            conflict_keys=["account_id", "comp_name", "platform"],
            normalizer=account_normalizer

        )
        return Result.ok("Şirket başarıyla kaydedildi.")
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


def process_logo(file_path: str, max_size: int = 256) -> tuple[str, QPixmap]:
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
