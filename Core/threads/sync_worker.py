from PyQt6.QtCore import QThread, pyqtSignal
from Feedback.processors.pipeline import Result, map_error_to_message


class SyncWorker(QThread):
    """
    Genel amaçlı senkron işler için worker.
    Örn: DB kayıt, dosya yazma, CPU-bound işlemler.
    """
    finished = pyqtSignal()
    result_ready = pyqtSignal(object)

    def __init__(self, func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}

    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)

            # Eğer fonksiyon Result dönüyorsa direkt gönder
            if isinstance(result, Result):
                self.result_ready.emit(result)
            else:
                # Result değilse sarmala
                self.result_ready.emit(
                    Result.ok("SyncWorker işlemi tamamlandı.", close_dialog=False, data={"result": result})
                )

        except Exception as e:
            res = Result.fail(map_error_to_message(e), error=e, close_dialog=False)
            self.result_ready.emit(res)
        finally:
            self.finished.emit()
