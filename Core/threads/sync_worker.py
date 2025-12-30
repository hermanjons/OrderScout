# Core/threads/sync_worker.py
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from Feedback.processors.pipeline import Result

try:
    from Feedback.processors.pipeline import map_error_to_message
except Exception:
    map_error_to_message = None


class SyncWorker(QThread):
    """
    Genel amaçlı senkron işler için worker.
    Örn: Network çağrısı, DB kayıt, CPU-bound işlemler.

    Kullanım:
        worker = SyncWorker(func, *args, **kwargs)
        worker.result_ready.connect(...)
        worker.finished.connect(...)
        worker.start()
    """
    finished = pyqtSignal()
    result_ready = pyqtSignal(object)
    progress = pyqtSignal(int, str)  # (percent, message) - opsiyonel

    def __init__(self, func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}

    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)

            if isinstance(result, Result):
                self.result_ready.emit(result)
            else:
                self.result_ready.emit(
                    Result.ok(
                        "SyncWorker işlemi tamamlandı.",
                        close_dialog=False,
                        data={"result": result},
                    )
                )

        except Exception as e:
            msg = None
            if map_error_to_message:
                try:
                    msg = map_error_to_message(e)
                except Exception:
                    msg = None
            msg = msg or str(e) or "Bilinmeyen hata"

            self.result_ready.emit(Result.fail(msg, error=e, close_dialog=False))
        finally:
            self.finished.emit()
