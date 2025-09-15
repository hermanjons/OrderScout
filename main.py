import sys
from PyQt6.QtWidgets import QApplication
from Main_interface.views import MainInterface
from sqlmodel import SQLModel
from Core.utils.model_utils import get_engine

if __name__ == "__main__":
    SQLModel.metadata.create_all(get_engine("orders.db"))  # tüm tablo sınıfları aynı metadata'ya kayıtlıysa yeterlidir
    app = QApplication(sys.argv)
    window = MainInterface()
    window.show()
    sys.exit(app.exec())
