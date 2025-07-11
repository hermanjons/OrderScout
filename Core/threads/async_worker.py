from PyQt6.QtCore import QThread, pyqtSignal
import asyncio


class AsyncWorker(QThread):
    finished = pyqtSignal(object)  # tek veri dönsün istersen tuple da olabilir

    def __init__(self, async_func, *args, parent=None):
        super().__init__(parent)
        self.async_func = async_func  # asenkron fonksiyon
        self.args = args  # parametreleri tuple olarak al
        self.kwargs = {}

    def run(self):
        print("run etti")
        try:

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.async_func(*self.args, **self.kwargs))
            self.finished.emit(result)
        except Exception as e:
            print("Worker Exception:", e)
