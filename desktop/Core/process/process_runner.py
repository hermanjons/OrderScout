# Core/utils/process_runner.py
from __future__ import annotations

import os
import sys
import json
from dataclasses import dataclass
from typing import Any, Optional, Callable, Dict, List, Union

from PyQt6.QtCore import QObject, QProcess, pyqtSignal, QProcessEnvironment

from Core.constants.paths import CORE_BASE_DIR
from Core.constants.process_constants import PROCESS_BUFFER_LIMIT_BYTES


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


# Projenin kök dizini (Core/utils/ içinden 3 geri çıkıyoruz)
_base_dir = str(CORE_BASE_DIR)


# -------------------------------
# ✅ Basit JSON Lines protokolü
# -------------------------------
# Worker STDOUT'a satır satır JSON yazabilir:
#   {"type":"log","message":"..."}
#   {"type":"progress","current":3,"total":10}
#   {"type":"result","success":true,"message":"ok","data":{...}}
#
# Runner:
#  - stdout_text: ham text akar
#  - message: JSON parse edilen her mesaj akar
#  - finished: "result" veya process bittiğinde elde edilen final dict döner


@dataclass
class ProcessTarget:
    """
    Dev mod: python <script_path>
    Frozen mod: sys.executable <args...>  (main router tarafı bunu handle etmeli)

    identifier:
      - Dev modda: script_path (mutlak veya BASE_DIR'e göre relative)
      - Frozen modda: worker_id (ör: "orders.db_save_worker") veya script path
    """
    identifier: str
    args: List[str] = None

    def __post_init__(self) -> None:
        if self.args is None:
            self.args = []


class GenericProcessRunner(QObject):
    """
    Genel amaçlı worker runner.

    Özellikler:
    - Dev/frozen ayrımı
    - STDIN'den JSON gönderme (tek sefer veya stream)
    - STDOUT/STDERR canlı izleme
    - STDOUT'ta JSON-lines parse edip 'message' sinyaliyle UI'a taşır
    - Final result yakalama: {"success":bool,"message":str,"data":...}
    """

    started = pyqtSignal()
    stdout_text = pyqtSignal(str)
    stderr_text = pyqtSignal(str)

    message = pyqtSignal(dict)     # STDOUT'tan parse edilen her JSON mesaj
    finished = pyqtSignal(dict)    # final result dict

    def __init__(
        self,
        target: ProcessTarget,
        *,
        initial_payload: Optional[Dict[str, Any]] = None,
        parent: Optional[QObject] = None,
        pythonpath_base: Optional[str] = None,
        frozen_args_builder: Optional[Callable[[ProcessTarget], List[str]]] = None,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__(parent)

        self.target = target
        self.initial_payload = initial_payload
        self.encoding = encoding

        self.process = QProcess(self)

        self._stdout_buf: bytes = b""
        self._stderr_buf: bytes = b""
        self._stdout_line_buf: str = ""  # JSONL için satır buffer

        self._final_result: Optional[dict] = None

        self.pythonpath_base = pythonpath_base or _base_dir

        # Frozen modda main router'ı nasıl çağıracağını belirler.
        # Default: <exe> --worker <identifier> [args...]
        self.frozen_args_builder = frozen_args_builder or self._default_frozen_args_builder

        # Signals
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_process_error)

    @staticmethod
    def _append_capped_bytes(buffer: bytes, chunk: bytes) -> bytes:
        merged = bytes(buffer or b"") + bytes(chunk or b"")
        if len(merged) <= PROCESS_BUFFER_LIMIT_BYTES:
            return merged
        return merged[-PROCESS_BUFFER_LIMIT_BYTES:]

    # -------------------------------------------------
    # Exec seçimi
    # -------------------------------------------------

    def _python_executable_dev(self) -> str:
        exe = sys.executable

        # venv içinden koşuyorsa aynen kullan
        if "venv" in exe.replace("\\", "/"):
            return exe

        venv_win = os.path.join(_base_dir, "venv", "Scripts", "python.exe")
        if os.path.exists(venv_win):
            return venv_win

        venv_nix = os.path.join(_base_dir, "venv", "bin", "python")
        if os.path.exists(venv_nix):
            return venv_nix

        return exe

    def _default_frozen_args_builder(self, target: ProcessTarget) -> List[str]:
        # main.py router tarafında bunu handle etmen gerekecek:
        # OrderScout.exe --worker <identifier> [args...]
        return ["--worker", target.identifier, *target.args]

    def _resolve_script_path(self, identifier: str) -> str:
        # Dev modda identifier çoğunlukla "Orders/processors/xxx.py" olur
        if os.path.isabs(identifier):
            return identifier
        return os.path.join(_base_dir, identifier)

    # -------------------------------------------------
    # Start / Stop / Send
    # -------------------------------------------------

    def start(self, *, wait_started_ms: int = 4000) -> None:
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", self.encoding)
        env.insert("PYTHONUTF8", "1")

        # DEV modda importlar için PYTHONPATH ekle
        if not is_frozen():
            existing_pp = env.value("PYTHONPATH", "")
            base = self.pythonpath_base
            if existing_pp:
                env.insert("PYTHONPATH", base + os.pathsep + existing_pp)
            else:
                env.insert("PYTHONPATH", base)

        self.process.setProcessEnvironment(env)

        if is_frozen():
            program = sys.executable
            args = self.frozen_args_builder(self.target)
        else:
            program = self._python_executable_dev()
            script_path = self._resolve_script_path(self.target.identifier)
            if not os.path.exists(script_path):
                msg = f"Worker script bulunamadı: {script_path}"
                self.stderr_text.emit(msg)
                self.finished.emit({"success": False, "message": msg, "data": None})
                return
            args = [script_path, *self.target.args]

        self.process.start(program, args)

        if not self.process.waitForStarted(wait_started_ms):
            msg = f"Process başlatılamadı. program={program} args={args}"
            self.stderr_text.emit(msg)
            self.finished.emit({"success": False, "message": msg, "data": None})
            return

        self.started.emit()

        # initial payload varsa gönder
        if self.initial_payload is not None:
            self.send_json(self.initial_payload, close_stdin=False)

    def terminate(self, *, kill_after_ms: int = 1500) -> None:
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        self.process.terminate()
        if not self.process.waitForFinished(kill_after_ms):
            self.process.kill()

    def close_stdin(self) -> None:
        try:
            self.process.closeWriteChannel()
        except Exception:
            pass

    def send_json(self, payload: Dict[str, Any], *, close_stdin: bool = False) -> None:
        """
        Worker'a JSON gönderir.
        Protokol önerisi: JSON-lines → her gönderimde '\n' ekliyoruz.
        """
        try:
            data = json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            self.stderr_text.emit(f"Payload JSON'a çevrilemedi: {e}")
            return

        try:
            self.process.write((data + "\n").encode(self.encoding))
            if close_stdin:
                self.close_stdin()
        except Exception as e:
            self.stderr_text.emit(f"STDIN write hatası: {e}")

    # -------------------------------------------------
    # IO handlers
    # -------------------------------------------------

    def _emit_stdout_text(self, text: str) -> None:
        if text:
            self.stdout_text.emit(text)

    def _emit_stderr_text(self, text: str) -> None:
        if text:
            self.stderr_text.emit(text)

    def _handle_json_line(self, line: str) -> None:
        """
        STDOUT'tan gelen tek satır JSON'u parse eder.
        Parse olmazsa ignore (ama stdout_text zaten ham akıyor).
        """
        line = line.strip()
        if not line:
            return

        try:
            obj = json.loads(line)
        except Exception:
            return

        if isinstance(obj, dict):
            self.message.emit(obj)

            # "result" mesajı gelirse final olarak kabul et
            if obj.get("type") == "result":
                # Beklenen:
                # {"type":"result","success":True/False,"message":"...","data":...}
                self._final_result = {
                    "success": bool(obj.get("success", False)),
                    "message": obj.get("message", ""),
                    "data": obj.get("data", None),
                }

    def _on_stdout(self) -> None:
        chunk = self.process.readAllStandardOutput().data()
        if not chunk:
            return

        self._stdout_buf = self._append_capped_bytes(self._stdout_buf, chunk)

        try:
            text = chunk.decode(self.encoding, errors="ignore")
        except Exception:
            text = str(chunk)

        self._emit_stdout_text(text)

        # JSONL parse (satır bazlı)
        self._stdout_line_buf += text
        while "\n" in self._stdout_line_buf:
            line, self._stdout_line_buf = self._stdout_line_buf.split("\n", 1)
            self._handle_json_line(line)

    def _on_stderr(self) -> None:
        chunk = self.process.readAllStandardError().data()
        if not chunk:
            return

        self._stderr_buf = self._append_capped_bytes(self._stderr_buf, chunk)

        try:
            text = chunk.decode(self.encoding, errors="ignore")
        except Exception:
            text = str(chunk)

        self._emit_stderr_text(text)

    def _on_process_error(self, _err) -> None:
        msg = "Process error occurred."
        try:
            msg += f" (program={self.process.program()} args={self.process.arguments()})"
        except Exception:
            pass
        self._emit_stderr_text(msg)

    def _on_finished(self) -> None:
        """
        Process bittiğinde final result üret:
        - Worker yalnızca JSONL `type=result` mesajı ile sonuç üretir.
        - Bu mesaj yoksa hata döneriz.
        """

        # JSONL result geldi mi?
        if self._final_result is not None:
            self.finished.emit(self._final_result)
            return

        # Sonuç mesajı yoksa
        stderr_preview = ""
        if self._stderr_buf:
            try:
                stderr_preview = self._stderr_buf.decode(self.encoding, errors="ignore")[-1200:]
            except Exception:
                stderr_preview = str(self._stderr_buf)[-1200:]

        msg = "Worker process `type=result` mesajı üretmedi."
        if stderr_preview.strip():
            msg += f"\n--- STDERR ---\n{stderr_preview}"

        self.finished.emit({"success": False, "message": msg, "data": None})
