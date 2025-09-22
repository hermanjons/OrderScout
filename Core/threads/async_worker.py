from PyQt6.QtCore import QThread, pyqtSignal
import asyncio
from Feedback.processors.pipeline import Result, map_error_to_message


class AsyncWorker(QThread):
    finished = pyqtSignal()            # sadece "işlem bitti" mesajı
    result_ready = pyqtSignal(object)  # veri taşıyan sinyal

    def __init__(self, async_func, *args, parent=None, kwargs=None):
        super().__init__(parent)
        self.async_func = async_func
        self.args = args
        self.kwargs = kwargs or {}  # Ekstra named argümanlar (örnek: progress_callback)

    def run(self):
        print("run etti")
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.async_func(*self.args, **self.kwargs))
            if not isinstance(result, Result):
                result = Result.ok("AsyncWorker sonucu", data={"raw": result})

            self.result_ready.emit(result)
            self.finished.emit()
        except Exception as e:
            err_res = Result.fail(f"Worker Exception: {str(e)}", error=e)
            self.result_ready.emit(err_res)
            self.finished.emit()

