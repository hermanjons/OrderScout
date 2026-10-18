from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication

from Update.constants.ui_constants import (
    UPDATE_RUNNER_BADGE_DONE_TEXT,
    UPDATE_RUNNER_BADGE_FAILED_TEXT,
    UPDATE_RUNNER_BADGE_RUNNING_TEXT,
    UPDATE_RUNNER_DETAIL_DONE_TEXT,
    UPDATE_RUNNER_DETAIL_FAILED_TEXT,
    UPDATE_RUNNER_STAGE_DONE_TEXT,
    UPDATE_RUNNER_STAGE_FAILED_TEXT,
    UPDATE_RUNNER_STAGE_PREPARING_TEXT,
    UPDATE_RUNNER_STAGE_RUNNING_TEXT,
)
from .updater_runner_dialog import UpdaterRunnerDialog


def _load_runner_payload(payload_path: Path) -> dict[str, Any]:
    raw = payload_path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("Runner payload invalid.")
    return parsed


def _write_runner_state(state_path: Path, *, status: str, progress: int, message: str) -> None:
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": str(status or "").strip(),
            "progress": max(0, min(100, int(progress or 0))),
            "message": str(message or "").strip(),
        }
        state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _latest_log_line(path: Path) -> str:
    try:
        if not path.exists():
            return ""
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in reversed(lines):
            text = str(line or "").strip()
            if text:
                return text
    except Exception:
        return ""
    return ""


def _normalize_detail(text: str) -> str:
    cleaned = " ".join(str(text or "").replace("\x00", " ").split())
    return cleaned.strip()


def _stage_from_log_line(line: str) -> str:
    lower = str(line or "").strip().lower()
    if not lower:
        return UPDATE_RUNNER_STAGE_RUNNING_TEXT
    if "preparing to install" in lower or "starting install" in lower:
        return UPDATE_RUNNER_STAGE_PREPARING_TEXT
    if "file entry" in lower or "installing the file" in lower:
        return "Dosyalar yerleştiriliyor..."
    if "creating icons" in lower or "icon" in lower or "shortcut" in lower:
        return "Kısayollar hazırlanıyor..."
    if "registry" in lower:
        return "Sistem kayıtları güncelleniyor..."
    if "finishing installation" in lower or "finalizing" in lower:
        return "Son kontroller yapılıyor..."
    return UPDATE_RUNNER_STAGE_RUNNING_TEXT


class InstallerRunnerController(QObject):
    def __init__(self, payload_path: str, parent=None):
        super().__init__(parent)
        self._payload_path = Path(str(payload_path or "").strip()).expanduser()
        self._payload = _load_runner_payload(self._payload_path)
        self._dialog = UpdaterRunnerDialog()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(260)
        self._poll_timer.timeout.connect(self._poll_installer)
        self._target_watch_timer = QTimer(self)
        self._target_watch_timer.setInterval(500)
        self._target_watch_timer.timeout.connect(self._poll_target_startup)
        self._proc: subprocess.Popen | None = None
        self._target_proc: subprocess.Popen | None = None
        self._target_watch_started_at = 0.0
        self._last_line = ""
        self._pulse = 8
        self._stall_ticks = 0

        self._installer_path = Path(str(self._payload.get("installer_path") or "").strip())
        self._target_dir = Path(str(self._payload.get("target_dir") or "").strip())
        self._installer_log = Path(str(self._payload.get("installer_log") or "").strip())
        self._runner_state = Path(str(self._payload.get("runner_state") or "").strip())
        self._target_exe = Path(str(self._payload.get("target_exe") or "").strip())
        self._previous_exe = Path(str(self._payload.get("previous_exe") or "").strip())
        try:
            watch_seconds = float(self._payload.get("startup_watch_seconds") or 12.0)
        except Exception:
            watch_seconds = 12.0
        self._startup_watch_seconds = max(3.0, min(45.0, watch_seconds))

    def start(self) -> None:
        self._dialog.set_badge(UPDATE_RUNNER_BADGE_RUNNING_TEXT, kind="info")
        self._dialog.set_stage(UPDATE_RUNNER_STAGE_PREPARING_TEXT)
        self._dialog.set_detail("Yeni sürüm paketi açılıyor.")
        self._dialog.set_progress(self._pulse)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
        _write_runner_state(
            self._runner_state,
            status="ui_ready",
            progress=self._pulse,
            message="Updater UI ready.",
        )
        QTimer.singleShot(220, self._launch_installer)

    def _launch_installer(self) -> None:
        if self._installer_log.exists():
            try:
                self._installer_log.unlink(missing_ok=True)
            except Exception:
                pass

        if not self._installer_path.exists():
            self._finish_failure("Kurulum paketi bulunamadı.")
            return

        args = [
            str(self._installer_path),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            f"/LOG={self._installer_log}",
            f"/DIR={self._target_dir}",
        ]
        try:
            creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
            self._proc = subprocess.Popen(
                args,
                close_fds=True,
                creationflags=creation_flags,
            )
        except Exception as exc:
            self._finish_failure(f"Kurulum başlatılamadı: {exc}")
            return

        self._pulse = 12
        self._dialog.set_progress(self._pulse)
        self._dialog.set_stage("Kurulum başlatıldı...")
        self._dialog.set_detail("Dosyalar hedef klasöre yazılıyor.")
        _write_runner_state(
            self._runner_state,
            status="installer_started",
            progress=self._pulse,
            message="Installer process started.",
        )
        self._poll_timer.start()

    def _poll_installer(self) -> None:
        proc = self._proc
        if proc is None:
            return

        current_line = _latest_log_line(self._installer_log)
        progress_changed = False
        if current_line and current_line != self._last_line:
            self._last_line = current_line
            self._stall_ticks = 0
            stage = _stage_from_log_line(current_line)
            detail = _normalize_detail(current_line)
            self._pulse = min(94, self._pulse + 4)
            self._update_running_ui(stage=stage, detail=detail, progress=self._pulse)
            progress_changed = True

        if proc.poll() is None and not progress_changed:
            self._stall_ticks = min(9999, self._stall_ticks + 1)
            step = 0
            if self._pulse < 28:
                step = 2
            elif self._pulse < 84:
                step = 1
            elif self._pulse < 96 and self._stall_ticks % 4 == 0:
                step = 1
            if step > 0:
                self._pulse = min(96, self._pulse + step)
                stage = self._dialog._stage.text().strip() or UPDATE_RUNNER_STAGE_RUNNING_TEXT
                detail = self._dialog._detail.text().strip() or "Dosyalar yerleştiriliyor."
                self._update_running_ui(stage=stage, detail=detail, progress=self._pulse)

        if proc.poll() is not None:
            self._poll_timer.stop()
            if int(proc.returncode or 0) == 0:
                self._finish_success()
            else:
                self._finish_failure(f"Kurulum tamamlanamadı (Kod: {int(proc.returncode or 0)}).")

    def _update_running_ui(self, *, stage: str, detail: str, progress: int) -> None:
        self._dialog.set_badge(UPDATE_RUNNER_BADGE_RUNNING_TEXT, kind="info")
        self._dialog.set_stage(stage)
        self._dialog.set_detail(detail)
        self._dialog.set_progress(progress)
        _write_runner_state(
            self._runner_state,
            status="running",
            progress=progress,
            message=stage,
        )

    def _launch_path(self, path: Path) -> subprocess.Popen | None:
        if not path.exists():
            return None
        try:
            if os.name == "nt" and path.suffix.lower() == ".exe":
                return subprocess.Popen([str(path)], close_fds=True)
            else:
                os.startfile(str(path))  # type: ignore[attr-defined]
                return None
        except Exception:
            return None

    def _finish_target_startup_failure(self, *, exit_code: int | None, reason: str) -> None:
        self._target_watch_timer.stop()
        self._dialog.set_badge(UPDATE_RUNNER_BADGE_FAILED_TEXT, kind="error")
        self._dialog.set_stage("Yeni sürüm açılamadı.")
        self._dialog.set_detail("Önceki sürüm otomatik olarak geri yükleniyor.")
        self._dialog.set_progress(100)
        self._dialog.allow_close(True)
        _write_runner_state(
            self._runner_state,
            status="rolled_back",
            progress=100,
            message="New version failed during startup; rollback requested.",
        )

        rollback_exe = self._previous_exe
        try:
            from Update.processors.pipeline import rollback_installed_update

            rollback_res = rollback_installed_update(
                current_exe=str(self._target_exe),
                reason=reason,
                notify_user=True,
                exit_code=exit_code,
            )
            if rollback_res.success:
                rollback_path = str((rollback_res.data or {}).get("rollback_exe") or "").strip()
                if rollback_path:
                    rollback_exe = Path(rollback_path)
        except Exception:
            pass

        self._launch_path(rollback_exe)
        QTimer.singleShot(1800, QApplication.instance().quit)

    def _poll_target_startup(self) -> None:
        proc = self._target_proc
        if proc is None:
            self._target_watch_timer.stop()
            QTimer.singleShot(300, QApplication.instance().quit)
            return

        exit_code = proc.poll()
        if exit_code is None:
            elapsed = time.monotonic() - self._target_watch_started_at
            if elapsed >= self._startup_watch_seconds:
                self._target_watch_timer.stop()
                _write_runner_state(
                    self._runner_state,
                    status="startup_verified",
                    progress=100,
                    message="New version stayed alive through startup watch.",
                )
                QTimer.singleShot(300, QApplication.instance().quit)
            return

        if int(exit_code or 0) != 0:
            self._finish_target_startup_failure(
                exit_code=int(exit_code or 0),
                reason="target_crashed_before_decision",
            )
            return

        self._finish_target_startup_failure(
            exit_code=0,
            reason="target_exited_before_decision",
        )

    def _finish_success(self) -> None:
        self._dialog.set_badge(UPDATE_RUNNER_BADGE_DONE_TEXT, kind="ok")
        self._dialog.set_stage(UPDATE_RUNNER_STAGE_DONE_TEXT)
        self._dialog.set_detail(UPDATE_RUNNER_DETAIL_DONE_TEXT)
        self._dialog.set_progress(100)
        self._dialog.allow_close(True)
        _write_runner_state(
            self._runner_state,
            status="completed",
            progress=100,
            message="Update completed.",
        )
        if not self._target_exe.exists():
            self._launch_path(self._previous_exe)
            QTimer.singleShot(1200, QApplication.instance().quit)
            return

        self._dialog.set_stage("Yeni sürüm doğrulanıyor...")
        self._dialog.set_detail("Uygulama açılışı kısa süre izleniyor.")
        try:
            from Update.processors.pipeline import mark_update_target_launch_attempted

            mark_update_target_launch_attempted(target_exe=str(self._target_exe))
        except Exception:
            pass
        self._target_proc = self._launch_path(self._target_exe)
        if self._target_proc is None:
            self._finish_target_startup_failure(
                exit_code=None,
                reason="target_launch_failed_before_decision",
            )
            return

        self._target_watch_started_at = time.monotonic()
        _write_runner_state(
            self._runner_state,
            status="verifying_startup",
            progress=100,
            message="New version launched; monitoring startup.",
        )
        self._target_watch_timer.start()

    def _finish_failure(self, message: str) -> None:
        self._dialog.set_badge(UPDATE_RUNNER_BADGE_FAILED_TEXT, kind="error")
        self._dialog.set_stage(UPDATE_RUNNER_STAGE_FAILED_TEXT)
        self._dialog.set_detail(str(message or "").strip() or UPDATE_RUNNER_DETAIL_FAILED_TEXT)
        self._dialog.set_progress(0)
        self._dialog.allow_close(True)
        _write_runner_state(
            self._runner_state,
            status="failed",
            progress=0,
            message=str(message or "").strip(),
        )
        rollback_exe = self._previous_exe
        try:
            from Update.processors.pipeline import rollback_installed_update

            rollback_res = rollback_installed_update(
                current_exe=str(self._target_exe),
                reason="installer_failed",
                notify_user=True,
            )
            if rollback_res.success:
                rollback_path = str((rollback_res.data or {}).get("rollback_exe") or "").strip()
                if rollback_path:
                    rollback_exe = Path(rollback_path)
        except Exception:
            pass

        self._launch_path(rollback_exe)
        QTimer.singleShot(1800, QApplication.instance().quit)


def run_update_runner(payload_path: str) -> int:
    payload = Path(str(payload_path or "").strip()).expanduser()
    if not payload.exists():
        raise SystemExit(f"Missing updater payload: {payload}")

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication([sys.argv[0], "--update-runner", str(payload)])
    assert app is not None
    app.setQuitOnLastWindowClosed(False)

    controller = InstallerRunnerController(str(payload))
    QTimer.singleShot(0, controller.start)

    if owns_app:
        return int(app.exec())
    return 0
