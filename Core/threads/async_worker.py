from PyQt6.QtCore import QThread, pyqtSignal
import asyncio


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

            # 🔥 sonucu önce yay, sonra "bitti" sinyali
            self.result_ready.emit(result)
            self.finished.emit()
        except Exception as e:
            print("Worker Exception:", e)
