# Core/utils/process_runner.py
from __future__ import annotations

import os
import sys
import json
from typing import Dict, Any, Optional

from PyQt6.QtCore import QProcess, QObject, pyqtSignal, QProcessEnvironment


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


# Projenin kök dizini (dev mod için)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


class DBSaveProcess(QObject):
    """
    DB save işini ayrı process'te çalıştırır.

    DEV:
      python db_save_worker.py (venv python) ile çalıştırır.

    EXE (frozen):
      Aynı EXE'yi "--db-save-worker" argümanı ile çalıştırır.
      (GUI açmadan worker mode çalışacak şekilde main.py router şart!)
    """

    finished = pyqtSignal(dict)   # {"success": bool, "message": str, "data": {...}}
    error = pyqtSignal(str)       # STDERR logları / başlanamama vs.

    def __init__(self, payload: Dict[str, Any], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.payload = payload
        self.process = QProcess(self)

        self._stdout_buf: bytes = b""
        self._stderr_buf: bytes = b""

        # Sinyaller
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)

        # (İsteğe bağlı) Daha stabil: process crash ederse de yakala
        self.process.errorOccurred.connect(self._on_process_error)

    # -------------------------------------------------

    def _python_executable_dev(self) -> str:
        """
        DEV ortamda mümkünse venv python bulur.
        """
        exe = sys.executable

        # 1) sys.executable venv ise
        if "venv" in exe.replace("\\", "/"):
            return exe

        # 2) BASE_DIR/venv/Scripts/python.exe
        venv_win = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
        if os.path.exists(venv_win):
            return venv_win

        # 3) BASE_DIR/venv/bin/python
        venv_nix = os.path.join(BASE_DIR, "venv", "bin", "python")
        if os.path.exists(venv_nix):
            return venv_nix

        return exe

    # -------------------------------------------------

    def start(self) -> None:
        """
        Process'i başlatır ve payload'ı JSON olarak STDIN'den gönderir.
        """
        # Ortam değişkenleri
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")

        # DEV modda importlar için PYTHONPATH ekleyelim
        if not _is_frozen():
            existing_pp = env.value("PYTHONPATH", "")
            if existing_pp:
                env.insert("PYTHONPATH", BASE_DIR + os.pathsep + existing_pp)
            else:
                env.insert("PYTHONPATH", BASE_DIR)

        self.process.setProcessEnvironment(env)

        # --- Komut seçimi ---
        if _is_frozen():
            # ✅ EXE: aynı exe'yi worker modda çalıştır
            program = sys.executable  # OrderScout.exe
            args = ["--db-save-worker"]
        else:
            # ✅ DEV: python ile script çalıştır
            worker_path = os.path.join(BASE_DIR, "Orders", "processors", "db_save_worker.py")
            if not os.path.exists(worker_path):
                msg = f"db_save_worker bulunamadı: {worker_path}"
                self.error.emit(msg)
                self.finished.emit({"success": False, "message": msg, "data": None})
                return

            program = self._python_executable_dev()
            args = [worker_path]

        # Process'i başlat
        self.process.start(program, args)

        if not self.process.waitForStarted(4000):
            msg = f"db_save_worker process'i başlatılamadı (timeout). program={program} args={args}"
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
        # QProcess errorOccurred: daha anlamlı mesaj üret
        msg = "db_save_worker process error occurred."
        try:
            msg += f" (program={self.process.program()} args={self.process.arguments()})"
        except Exception:
            pass
        self.error.emit(msg)

    def _on_finished(self) -> None:
        """
        Process tamamen bittiğinde STDOUT JSON parse edilir.
        Sadece son dolu satırı JSON kabul eder (debug print karışmasın diye).
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

        self.finished.emit(result)
