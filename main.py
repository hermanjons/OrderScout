# main.py
from __future__ import annotations

import sys

from sqlmodel import SQLModel
from Core.utils.model_utils import get_engine

# License modelleri metadata'ya dahil olsun diye import (kullanmıyoruz ama create_all için şart)
from License.models import LicenseActionLog, LocalLicenseState, FreemiusEventLog  # noqa: F401
from Account.models import *
from Orders.models.trendyol.trendyol_models import *



def _run_db_save_worker_mode() -> None:
    """
    Aynı EXE içerisinden ayrı process worker mode.
    GUI açılmaz. stdin'den JSON alır, stdout'a JSON basar.
    """
    from Orders.processors.db_save_worker import main as worker_main
    worker_main()


def _cli_router() -> bool:
    """
    True dönerse program GUI açmadan çıkacak demektir.
    """
    if "--db-save-worker" in sys.argv:
        _run_db_save_worker_mode()
        return True
    return False


def _bootstrap_db() -> None:
    """
    DB tablolarını hazırlar. Worker modda da lazım olabilir.
    """
    SQLModel.metadata.create_all(get_engine("orders.db"))


def main() -> int:
    # 1) CLI router (GUI öncesi!)
    if _cli_router():
        return 0

    # 2) Normal GUI flow
    _bootstrap_db()

    from PyQt6.QtWidgets import QApplication
    from Main_interface.views import MainInterface

    app = QApplication(sys.argv)
    window = MainInterface()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
