# Core/utils/process_runner.py
from __future__ import annotations

import os
import sys
import json
from typing import Dict, Any, Optional

from PyQt6.QtCore import QProcess, QObject, pyqtSignal, QProcessEnvironment
from Orders.signals.signals import order_signals

def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


# Projenin kök dizini (Core/utils/ içinden 3 geri çıkıyoruz)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


class DBSaveProcess(QObject):
    """
    DB save işini ayrı process'te çalıştırır.

    DEV:
      python Orders/processors/db_save_worker.py

    EXE (frozen):
      aynı exe'yi "--db-save-worker" argümanı ile çalıştırır.
      (GUI açmadan worker mode çalışacak şekilde main router şart!)
    """

    finished = pyqtSignal(dict)   # {"success": bool, "message": str, "data": {...}}
    error = pyqtSignal(str)       # STDERR logları

    def __init__(self, payload: Dict[str, Any], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.payload = payload
        self.process = QProcess(self)

        self._stdout_buf: bytes = b""
        self._stderr_buf: bytes = b""

        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_process_error)

    # -------------------------------------------------

    def _python_executable_dev(self) -> str:
        exe = sys.executable

        if "venv" in exe.replace("\\", "/"):
            return exe

        venv_win = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
        if os.path.exists(venv_win):
            return venv_win

        venv_nix = os.path.join(BASE_DIR, "venv", "bin", "python")
        if os.path.exists(venv_nix):
            return venv_nix

        return exe

    # -------------------------------------------------

    def start(self) -> None:
        """
        Process'i başlatır ve payload'ı JSON olarak STDIN'den gönderir.
        """
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")

        # DEV modda importlar için PYTHONPATH ekle
        if not _is_frozen():
            existing_pp = env.value("PYTHONPATH", "")
            if existing_pp:
                env.insert("PYTHONPATH", BASE_DIR + os.pathsep + existing_pp)
            else:
                env.insert("PYTHONPATH", BASE_DIR)

        self.process.setProcessEnvironment(env)

        # --- Komut seçimi ---
        if _is_frozen():
            program = sys.executable  # OrderScout.exe
            args = ["--db-save-worker"]
        else:
            worker_path = os.path.join(BASE_DIR, "Orders", "processors", "db_save_worker.py")
            if not os.path.exists(worker_path):
                msg = f"db_save_worker bulunamadı: {worker_path}"
                self.error.emit(msg)
                self.finished.emit({"success": False, "message": msg, "data": None})
                return

            program = self._python_executable_dev()
            args = [worker_path]

        self.process.start(program, args)

        if not self.process.waitForStarted(4000):
            msg = f"db_save_worker process'i başlatılamadı. program={program} args={args}"
            self.error.emit(msg)
            self.finished.emit({"success": False, "message": msg, "data": None})
            return

        # Payload'ı JSON olarak gönder
        try:
            payload_json = json.dumps(self.payload, ensure_ascii=False)
        except Exception as e:
            msg = f"Payload JSON'a çevrilemedi: {e}"
            self.error.emit(msg)
            self.finished.emit({"success": False, "message": msg, "data": None})
            return

        self.process.write(payload_json.encode("utf-8"))
        self.process.closeWriteChannel()

    # -------------------------------------------------

    def _on_stdout(self) -> None:
        self._stdout_buf += self.process.readAllStandardOutput().data()

    def _on_stderr(self) -> None:
        chunk = self.process.readAllStandardError().data()
        self._stderr_buf += chunk
        try:
            text = chunk.decode("utf-8", errors="ignore")
        except Exception:
            text = str(chunk)

        if text.strip():
            self.error.emit(text)

    def _on_process_error(self, _err) -> None:
        msg = "db_save_worker process error occurred."
        try:
            msg += f" (program={self.process.program()} args={self.process.arguments()})"
        except Exception:
            pass
        self.error.emit(msg)

    # -------------------------------------------------

    @staticmethod
    def _should_emit_orders_changed(result: dict) -> bool:
        """
        save_orders_to_db dönüşüne göre sadece DB gerçekten değiştiyse True.
        Beklenen format:
          {"success": True, "data": {"changed": bool, "counts": {...}}}
        """
        if result.get("success") is not True:
            return False
        data = result.get("data")
        if not isinstance(data, dict):
            return False
        return bool(data.get("changed", False))

    def _emit_orders_changed(self) -> None:
        """
        UI process içinde orders_changed emit eder.
        """
        try:

            order_signals.orders_changed.emit()
        except Exception:
            pass

    def _on_finished(self) -> None:
        """
        Process tamamen bittiğinde STDOUT JSON parse edilir.
        Sadece son dolu satırı JSON kabul eder.
        """
        if not self._stdout_buf:
            msg = "db_save_worker çıktı üretmedi."
            self.finished.emit({"success": False, "message": msg, "data": None})
            return

        try:
            out_str = self._stdout_buf.decode("utf-8", errors="ignore")
            lines = [line for line in out_str.splitlines() if line.strip()]
            if not lines:
                msg = "db_save_worker: Boş satırlardan başka çıktı yok."
                self.finished.emit({"success": False, "message": msg, "data": None})
                return

            json_str = lines[-1]
            result = json.loads(json_str)

            if not isinstance(result, dict):
                result = {
                    "success": False,
                    "message": "db_save_worker geçersiz çıktı formatı.",
                    "data": json_str,
                }

        except Exception as e:
            msg = f"db_save_worker output parse hatası: {e}"
            self.finished.emit({"success": False, "message": msg, "data": None})
            return

        # ✅ SADECE DB değiştiyse tetikle (performans)
        if self._should_emit_orders_changed(result):
            self._emit_orders_changed()

        self.finished.emit(result)
