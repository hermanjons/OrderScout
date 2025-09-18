from PyQt6.QtWidgets import QMessageBox
import logging

# -------------------------------------------------
# 📂 Logger Yapılandırması
# -------------------------------------------------
logger = logging.getLogger("orderscout")

if not logger.handlers:  # tekrar tekrar handler eklenmesin
    handler = logging.FileHandler("orderscout.log", encoding="utf-8")
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# -------------------------------------------------
# 📦 Result Sınıfı (işlem sonuç standardı)
# -------------------------------------------------
class Result:
    def __init__(
            self,
            success: bool,
            message: str = "",
            error: Exception = None,
            close_dialog: bool = True,
    ):
        self.success = success
        self.message = message
        self.error = error
        self.close_dialog = close_dialog

    @classmethod
    def ok(cls, message="", close_dialog=True):
        return cls(True, message, close_dialog=close_dialog)

    @classmethod
    def fail(cls, message="", error=None, close_dialog=False):
        return cls(False, message, error=error, close_dialog=close_dialog)


# -------------------------------------------------
# 💬 MessageHandler (UI + Logging)
# -------------------------------------------------
class MessageHandler:
    @staticmethod
    def show(dialog, result: Result):
        """
        İşlem sonucunu kullanıcıya gösterir ve hataları loglar.
        """
        if result.success:
            QMessageBox.information(dialog, "Başarılı", result.message)
            if result.close_dialog:
                dialog.accept()
        else:
            QMessageBox.critical(dialog, "Hata", result.message)
            if result.error:
                # traceback dahil logla
                logger.exception(
                    f"[{type(result.error).__name__}] {result.error}",
                    exc_info=result.error
                )


# feedback/processors/pipeline.py içine ekle
def map_error_to_message(error: Exception) -> str:
    """
    Exception tipine göre kullanıcıya gösterilecek anlamlı mesaj döner.
    Teknik detaylar log dosyasında saklanır.
    """
    from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError, DatabaseError

    # SQL / DB hataları
    if isinstance(error, IntegrityError):
        return "Aynı kayıt zaten mevcut. Lütfen tekrar eklemeyin."
    elif isinstance(error, OperationalError):
        return "Veritabanı ile bağlantı kurulamadı. Lütfen daha sonra tekrar deneyin."
    elif isinstance(error, ProgrammingError):
        return "Sistemsel bir hata oluştu (SQL hatası). Yetkili ile iletişime geçin."
    elif isinstance(error, DatabaseError):
        return "Veritabanı hatası oluştu. Lütfen tekrar deneyin."

    # Bağlantı hataları
    elif isinstance(error, ConnectionError):
        return "Sunucuya bağlanılamadı. İnternet bağlantınızı kontrol edin."
    elif isinstance(error, TimeoutError):
        return "İşlem zaman aşımına uğradı. Daha sonra tekrar deneyin."

    # Dosya / IO hataları
    elif isinstance(error, FileNotFoundError):
        return "Gerekli dosya bulunamadı. Lütfen dosya yolunu kontrol edin."
    elif isinstance(error, PermissionError):
        return "Bu işlem için izin yok. Lütfen yetkilerinizi kontrol edin."
    elif isinstance(error, IsADirectoryError):
        return "Bir klasör dosya gibi seçildi. Lütfen geçerli bir dosya seçin."
    elif isinstance(error, OSError):
        return "Dosya veya sistem hatası oluştu."

    # Veri hataları
    elif isinstance(error, ValueError):
        return "Geçersiz değer girildi. Lütfen bilgilerinizi kontrol edin."
    elif isinstance(error, TypeError):
        return "Beklenmeyen veri tipi. Lütfen giriş bilgilerinizi kontrol edin."
    elif isinstance(error, KeyError):
        return "Beklenen bir alan bulunamadı. Lütfen bilgilerinizi kontrol edin."
    elif isinstance(error, IndexError):
        return "Liste erişimi hatalı. Lütfen girdilerinizi kontrol edin."

    # PyQt / GUI hataları
    elif isinstance(error, RuntimeError):
        return "Uygulama hatası oluştu. Lütfen işlemi yeniden deneyin."

    # Bilinmeyen hatalar
    else:
        return "Bilinmeyen bir hata oluştu. Lütfen tekrar deneyin."
