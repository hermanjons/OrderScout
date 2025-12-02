# Core/utils/process_runner.py
from __future__ import annotations

import os
import sys
import json
from typing import Dict, Any

from PyQt6.QtCore import QProcess, QObject, pyqtSignal


# Projenin kök dizini (Core/utils/ içinden 3 geri çıkıyoruz)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


class DBSaveProcess(QObject):
    """
    Orders/processors/db_save_worker.py script'ini ayrı bir process olarak çalıştırır.

    Akış:
      - INPUT  (stdin):  JSON payload  -> {"order_data_list": [...], "order_item_list": [...]}
      - OUTPUT (stdout): JSON result   -> {"success": bool, "message": str, "data": {...}}

    Sinyaller:
      - finished: Worker işini tamamen bitirdiğinde JSON dict döner.
      - error:    STDERR'e düşen log / hata mesajlarını iletir.
    """

    finished = pyqtSignal(dict)   # {"success": True/False, "message": str, "data": {...}}
    error = pyqtSignal(str)       # STDERR logları / başlanamama vs.

    def __init__(self, payload: Dict[str, Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.payload = payload
        self.process = QProcess(self)

        self._stdout_buf: bytes = b""
        self._stderr_buf: bytes = b""

        # Sinyaller
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)

    # ----------------------------------------------

    def _python_executable(self) -> str:
        """
        Mümkün olduğunca venv içindeki python'u kullanmaya çalış.
        Çoğu durumda sys.executable zaten venv'tir.
        """
        exe = sys.executable

        # 1) sys.executable zaten venv içindeyse onu kullan
        if "venv" in exe.replace("\\", "/"):
            return exe

        # 2) Proje kökünde venv/Scripts/python.exe (Windows)
        venv_win = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
        if os.path.exists(venv_win):
            return venv_win

        # 3) Proje kökünde venv/bin/python (Linux / macOS)
        venv_nix = os.path.join(BASE_DIR, "venv", "bin", "python")
        if os.path.exists(venv_nix):
            return venv_nix

        # 4) Son çare: sys.executable
        return exe

    # ----------------------------------------------

    def start(self) -> None:
        """
        Process'i başlatır ve payload'ı JSON olarak STDIN'den gönderir.
        """
        worker_path = os.path.join(BASE_DIR, "Orders", "processors", "db_save_worker.py")
        if not os.path.exists(worker_path):
            msg = f"db_save_worker bulunamadı: {worker_path}"
            print(msg)
            self.error.emit(msg)
            self.finished.emit({"success": False, "message": msg, "data": None})
            return

        python_exe = self._python_executable()

        # Ortam değişkenleri
        env = self.process.processEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")

        # PYTHONPATH'e proje kökünü ekle ki 'Orders', 'Core' import edilebilsin
        existing_pp = str(env.value("PYTHONPATH", ""))
        if existing_pp:
            env.insert("PYTHONPATH", BASE_DIR + os.pathsep + existing_pp)
        else:
            env.insert("PYTHONPATH", BASE_DIR)

        self.process.setProcessEnvironment(env)

        # Process'i başlat
        self.process.start(python_exe, [worker_path])

        if not self.process.waitForStarted(3000):
            msg = "db_save_worker process'i başlatılamadı (3s timeout)."
            print(msg)
            self.error.emit(msg)
            self.finished.emit({"success": False, "message": msg, "data": None})
            return

        # Payload'ı JSON olarak gönder
        try:
            payload_json = json.dumps(self.payload)
        except Exception as e:
            msg = f"Payload JSON'a çevrilemedi: {e}"
            print(msg)
            self.error.emit(msg)
            self.finished.emit({"success": False, "message": msg, "data": None})
            return

        self.process.write(payload_json.encode("utf-8"))
        self.process.closeWriteChannel()

    # ----------------------------------------------

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
            print("db_save_worker STDERR:", text)
            self.error.emit(text)

    def _on_finished(self) -> None:
        """
        Process tamamen bittiğinde çağrılır.
        STDOUT'taki JSON parse edilir.
        Debug print'ler karışmasın diye sadece SON dolu satırı JSON kabul eder.
        """
        if not self._stdout_buf:
            msg = "db_save_worker çıktı üretmedi."
            print(msg)
            self.finished.emit({"success": False, "message": msg, "data": None})
            return

        try:
            out_str = self._stdout_buf.decode("utf-8", errors="ignore")

            # Satırlara böl → boş olmayan son satırı JSON say
            lines = [line for line in out_str.splitlines() if line.strip()]
            if not lines:
                msg = "db_save_worker: Boş satırlardan başka çıktı yok."
                print(msg)
                self.finished.emit({"success": False, "message": msg, "data": None})
                return

            json_str = lines[-1]  # sadece son dolu satırı parse et
            result = json.loads(json_str)

            if not isinstance(result, dict):
                result = {
                    "success": False,
                    "message": "db_save_worker geçersiz çıktı formatı.",
                    "data": json_str,
                }

        except Exception as e:
            msg = f"db_save_worker output parse hatası: {e}"
            print(msg)
            self.finished.emit({"success": False, "message": msg, "data": None})
            return

        self.finished.emit(result)
