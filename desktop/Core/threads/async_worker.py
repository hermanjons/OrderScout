from PyQt6.QtCore import QThread, pyqtSignal
import asyncio
import inspect
import time
from Feedback.processors.pipeline import Result, map_error_to_message


class AsyncWorker(QThread):
    progress_changed = pyqtSignal(int, int)   # (current, total)
    result_ready = pyqtSignal(object)         # Result objesi
    finished = pyqtSignal()                   # tamamlandı

    def __init__(self, async_func, *args, parent=None, kwargs=None):
        super().__init__(parent)
        self.async_func = async_func
        self.args = args
        self.kwargs = dict(kwargs or {})

    def run(self):
        loop = None
        try:
            # Worker içinden progress emit edecek helper
            last_progress_emit = {"current": None, "total": None, "time": 0.0}

            def progress_callback(current, total):
                try:
                    current_i = int(current)
                    total_i = max(int(total), 1)
                except Exception:
                    current_i, total_i = 0, 1
                now = time.monotonic()
                is_terminal = current_i >= total_i
                same_value = (
                    last_progress_emit["current"] == current_i
                    and last_progress_emit["total"] == total_i
                )
                if same_value and not is_terminal:
                    return
                if not is_terminal and (now - float(last_progress_emit["time"] or 0.0)) < 0.05:
                    return
                last_progress_emit["current"] = current_i
                last_progress_emit["total"] = total_i
                last_progress_emit["time"] = now
                self.progress_changed.emit(current_i, total_i)

            try:
                sig = inspect.signature(self.async_func)
                accepts_progress = "progress_callback" in sig.parameters or any(
                    param.kind == inspect.Parameter.VAR_KEYWORD
                    for param in sig.parameters.values()
                )
            except (TypeError, ValueError):
                accepts_progress = False
            if accepts_progress and "progress_callback" not in self.kwargs:
                self.kwargs["progress_callback"] = progress_callback

            # Yeni event loop başlat
            loop = asyncio.new_event_loop()

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
            if loop is not None:
                try:
                    from Core.utils.request_utils import close_async_request_clients

                    loop.run_until_complete(close_async_request_clients())
                    loop.run_until_complete(asyncio.sleep(0.05))
                except Exception:
                    pass
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                try:
                    loop.close()
                except Exception:
                    pass
            self.finished.emit()


