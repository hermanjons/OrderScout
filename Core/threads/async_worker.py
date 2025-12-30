from PyQt6.QtCore import QThread, pyqtSignal
import asyncio
from Feedback.processors.pipeline import Result, map_error_to_message


class AsyncWorker(QThread):
    progress_changed = pyqtSignal(int, int)   # (current, total)
    result_ready = pyqtSignal(object)         # Result objesi
    finished = pyqtSignal()                   # tamamlandı

    def __init__(self, async_func, *args, parent=None, kwargs=None):
        super().__init__(parent)
        self.async_func = async_func
        self.args = args
        self.kwargs = kwargs or {}

    def run(self):
        try:
            # Worker içinden progress emit edecek helper
            def progress_callback(current, total):
                self.progress_changed.emit(current, total)

            # Eğer progress callback denenmişse override et
            # (Dışarıda lambda ile UI güncellemek yerine, sinyal kullansın)
            self.kwargs["progress_callback"] = progress_callback

            # Yeni event loop başlat
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            result = loop.run_until_complete(
                self.async_func(*self.args, **self.kwargs)
            )

            # Sonuç Result değilse sar
            if not isinstance(result, Result):
                result = Result.ok("AsyncWorker sonucu", data={"raw": result})

            self.result_ready.emit(result)

        except Exception as e:
            err = Result.fail(f"Worker Exception: {str(e)}", error=e)
            self.result_ready.emit(err)

        finally:
            self.finished.emit()


