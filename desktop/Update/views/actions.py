from __future__ import annotations

from datetime import datetime
from typing import Optional
import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from Core.threads.sync_worker import SyncWorker
from Core.views import AppMessageCenter
from Feedback.processors.pipeline import MessageHandler, Result
from Update.constants.ui_constants import (
    UPDATE_LAUNCHED_DIALOG_TITLE,
    UPDATE_READY_DIALOG_TITLE,
    UPDATE_STAGE_TEXT,
    UPDATE_STATUS_COMPLETED_TEXT,
    UPDATE_STATUS_PREPARING_TEXT,
    UPDATE_STATUS_READY_TEXT,
)
from Update.processors.pipeline import (
    accept_installed_update,
    check_for_updates,
    clear_update_state,
    download_and_prepare_update,
    evaluate_update_startup_state,
    is_runtime_updatable,
    launch_prepared_update,
    load_update_config,
    mark_update_decision_prompt_shown,
    mark_update_rollback_notice_seen,
    rollback_installed_update,
)
from Update.views.views import UpdateCenterDialog, UpdateProgressDialog
from settings import APP_VERSION


_STAGE_TEXT = dict(UPDATE_STAGE_TEXT)


def _format_bytes(value: int) -> str:
    size = max(0, int(value or 0))
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.2f} GB"


def _format_iso_date(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "-"
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return stamp.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return raw


class _UpdateDownloadWorker(QThread):
    progress_changed = pyqtSignal(int, str)
    result_ready = pyqtSignal(object)

    def __init__(self, *, release: dict, asset: dict, parent=None):
        super().__init__(parent)
        self.release = dict(release or {})
        self.asset = dict(asset or {})

    def run(self) -> None:
        try:
            def on_progress(stage: str, current: int, total: int) -> None:
                if int(total or 0) > 0:
                    percent = int((int(current or 0) / int(total)) * 100)
                else:
                    percent = 0
                stage_key = str(stage or "").strip().lower()
                stage_text = _STAGE_TEXT.get(stage_key, stage_key or "Çalışıyor")
                self.progress_changed.emit(max(0, min(100, percent)), stage_text)

            res = download_and_prepare_update(
                release=self.release,
                asset=self.asset,
                progress_callback=on_progress,
            )
            self.result_ready.emit(res)
        except Exception as e:
            self.result_ready.emit(Result.fail(str(e), error=e, close_dialog=False))


class UpdateController(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent = parent
        self._check_worker: Optional[SyncWorker] = None
        self._download_worker: Optional[_UpdateDownloadWorker] = None
        self._progress_dialog: Optional[UpdateProgressDialog] = None
        self._center_dialog: Optional[UpdateCenterDialog] = None
        self._download_in_center = False
        self._pending_release: dict = {}
        self._pending_asset: dict = {}
        self._last_check_result: Optional[Result] = None
        self._last_check_ts: float = 0.0
        self._check_blocked_until_ts: float = 0.0

    @staticmethod
    def _safe_int(value, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)

    def _check_cooldown_sec(self) -> int:
        try:
            cfg = load_update_config()
            req = cfg.get("request") if isinstance(cfg.get("request"), dict) else {}
            sec = self._safe_int(req.get("check_cooldown_sec", 10), 10)
            return max(3, min(300, sec))
        except Exception:
            return 10

    @staticmethod
    def _result_retry_after_sec(result: Result) -> int:
        if not isinstance(result, Result):
            return 0
        data = result.data if isinstance(result.data, dict) else {}
        sec = UpdateController._safe_int(data.get("retry_after_sec", 0), 0)
        return max(0, sec)

    @staticmethod
    def _runtime_executable_for_state() -> str:
        try:
            if bool(getattr(sys, "frozen", False)):
                return str(Path(sys.executable).resolve())
        except Exception:
            pass
        return ""

    @staticmethod
    def _is_frozen_runtime() -> bool:
        try:
            return bool(getattr(sys, "frozen", False))
        except Exception:
            return False

    @staticmethod
    def _launch_executable(path: str) -> bool:
        target = str(path or "").strip()
        if not target:
            return False
        try:
            exe_path = Path(target)
            if not exe_path.exists():
                return False
            subprocess.Popen([str(exe_path)], close_fds=True)
            return True
        except Exception:
            return False

    def process_post_update_startup(self) -> None:
        runtime_exe = self._runtime_executable_for_state()
        res = evaluate_update_startup_state(current_exe=runtime_exe)
        if not isinstance(res, Result) or not res.success:
            return
        data = res.data or {}
        action = str(data.get("action") or "").strip().lower()
        state = data.get("state") or {}

        if action == "clear_invalid":
            clear_update_state()
            return

        if action == "redirect":
            if not self._is_frozen_runtime():
                return
            target_exe = str(data.get("target_exe") or "").strip()
            if self._launch_executable(target_exe):
                app = QApplication.instance()
                if app is not None:
                    QTimer.singleShot(120, app.quit)
            return

        if action == "notify_rollback":
            release_version = str(state.get("release_version") or "").strip() or "?"
            AppMessageCenter.warning(
                self._parent,
                "Güncelleme Geri Alındı",
                (
                    f"v{release_version} güncellemesi açılışta doğrulanamadığı için "
                    "önceki çalışan sürüme otomatik geri dönüldü."
                ),
            )
            mark_update_rollback_notice_seen()
            clear_update_state()
            return

        if action == "auto_rollback":
            reason = str(data.get("reason") or "target_prompt_not_reached").strip()
            target_exe = str(data.get("target_exe") or state.get("target_exe") or "").strip()
            rollback_res = rollback_installed_update(
                current_exe=target_exe or runtime_exe,
                reason=reason,
                notify_user=True,
            )
            if not rollback_res.success:
                MessageHandler.show(self._parent, rollback_res, only_errors=True)
                return
            release_version = str(state.get("release_version") or "").strip() or "?"
            AppMessageCenter.warning(
                self._parent,
                "Güncelleme Geri Alındı",
                (
                    f"v{release_version} güncellemesi doğrulama sorusuna gelemeden kapandı. "
                    "Önceki çalışan sürümde devam ediliyor."
                ),
            )
            mark_update_rollback_notice_seen()
            clear_update_state()
            return

        if action != "prompt_decision":
            return

        release_version = str(state.get("release_version") or "").strip() or "?"
        mark_update_decision_prompt_shown(current_exe=runtime_exe)
        keep = AppMessageCenter.confirm(
            self._parent,
            "Güncelleme Doğrulaması",
            (
                f"Yeni sürüm açıldı: v{release_version}\n\n"
                "Bu sürümde kalmak istiyor musun?\n"
                "Hayır dersen önceki sürüme geri dönülecek."
            ),
            default_yes=True,
        )

        if keep:
            keep_res = accept_installed_update(
                current_exe=runtime_exe,
                cleanup_previous=True,
            )
            if not keep_res.success:
                # Keep the new version accepted even if old-version cleanup fails.
                keep_res_no_cleanup = accept_installed_update(
                    current_exe=runtime_exe,
                    cleanup_previous=False,
                )
                if not keep_res_no_cleanup.success:
                    MessageHandler.show(self._parent, keep_res, only_errors=True)
                    return
                AppMessageCenter.warning(
                    self._parent,
                    "Güncelleme Onaylandı",
                    "Yeni sürüm varsayılan olarak ayarlandı. Temizlik adımı otomatik tamamlanamadı.",
                )
                return
            AppMessageCenter.info(
                self._parent,
                "Güncelleme Onaylandı",
                "Yeni sürüm varsayılan olarak ayarlandı.",
            )
            return

        rollback_res = rollback_installed_update(current_exe=runtime_exe)
        if not rollback_res.success:
            MessageHandler.show(self._parent, rollback_res, only_errors=True)
            return

        rollback_exe = str((rollback_res.data or {}).get("rollback_exe") or "").strip()
        launched = self._launch_executable(rollback_exe)
        if not launched:
            MessageHandler.show(
                self._parent,
                Result.fail("Önceki sürüm exe dosyası başlatılamadı."),
                only_errors=True,
            )
            return

        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(120, app.quit)

    def schedule_startup_check(self) -> None:
        try:
            cfg = load_update_config()
            if not bool(cfg.get("enabled", True)):
                return
            if not bool(cfg.get("check_on_startup", True)):
                return
            delay = max(1000, int(cfg.get("startup_delay_ms") or 3000))
            QTimer.singleShot(
                delay,
                lambda: self.check_updates(
                    silent_if_latest=True,
                    silent_errors=True,
                    present_in_center=False,
                    prompt_on_available=False,
                ),
            )
        except Exception:
            pass

    def check_updates_from_toolbar(self) -> None:
        dialog = self._ensure_center_dialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.check_updates(
            silent_if_latest=False,
            silent_errors=False,
            present_in_center=True,
            prompt_on_available=False,
        )

    def _ensure_center_dialog(self) -> UpdateCenterDialog:
        if self._center_dialog is None:
            dialog = UpdateCenterDialog(self._parent)
            dialog.check_requested.connect(
                lambda: self.check_updates(
                    silent_if_latest=False,
                    silent_errors=False,
                    present_in_center=True,
                    prompt_on_available=False,
                )
            )
            dialog.install_requested.connect(self._start_download_from_center)
            dialog.destroyed.connect(lambda *_: setattr(self, "_center_dialog", None))
            self._center_dialog = dialog
            self._populate_center_static_fields()
        return self._center_dialog

    def _populate_center_static_fields(self) -> None:
        if self._center_dialog is None:
            return
        cfg = load_update_config()
        github = cfg.get("github") if isinstance(cfg.get("github"), dict) else {}
        owner = str(github.get("owner") or "-").strip() or "-"
        repo = str(github.get("repo") or "-").strip() or "-"
        channel = str(cfg.get("channel") or "stable").strip().lower() or "stable"
        self._center_dialog.set_versions(
            current_version=str(APP_VERSION or "-"),
            latest_version="-",
        )
        self._center_dialog.set_release_meta(title="-", published_at="-")
        self._center_dialog.set_asset_meta(
            asset_text="-",
            source_text=f"{owner}/{repo}",
        )
        if is_runtime_updatable():
            runtime_text = f"Otomatik kurulum: Bu cihazda destekleniyor. Kanal: {channel}"
        else:
            runtime_text = f"Otomatik kurulum: Bu ortamda devre dışı (paket hazırlanır). Kanal: {channel}"
        self._center_dialog.set_runtime_text(runtime_text)
        self._center_dialog.set_notes("Henüz kontrol yapılmadı.")
        self._center_dialog.set_status(UPDATE_STATUS_READY_TEXT, kind="idle")
        self._center_dialog.set_check_enabled(True)
        self._center_dialog.set_install_enabled(False)
        self._center_dialog.set_progress_visible(False)

    def check_updates(
        self,
        *,
        silent_if_latest: bool,
        silent_errors: bool,
        present_in_center: bool = False,
        prompt_on_available: bool = True,
    ) -> None:
        now = time.monotonic()

        if self._check_worker is not None and self._check_worker.isRunning():
            if present_in_center and self._center_dialog is not None:
                self._center_dialog.set_status("Sürüm kontrolü zaten çalışıyor.", kind="busy")
            return

        if now < self._check_blocked_until_ts:
            remain = max(1, int(self._check_blocked_until_ts - now))
            warn_text = f"GitHub hız limiti nedeniyle bekleme aktif ({remain} sn)."
            if present_in_center:
                self._ensure_center_dialog()
                if self._center_dialog is not None:
                    self._center_dialog.set_status(warn_text, kind="error")
                    self._center_dialog.set_notes(
                        "Çok sık denetim nedeniyle GitHub API geçici limit verdi.\n"
                        f"Lütfen {remain} saniye sonra tekrar dene."
                    )
                    self._center_dialog.set_install_enabled(False)
            elif not silent_errors:
                AppMessageCenter.warning(self._parent, "Güncelleme", warn_text)
            return

        cooldown = self._check_cooldown_sec()
        if self._last_check_result is not None and (now - self._last_check_ts) < float(cooldown):
            remain = max(1, int(cooldown - (now - self._last_check_ts)))
            if present_in_center and self._center_dialog is not None:
                self._center_dialog.set_status(
                    f"Çok sık denetim algılandı. Önbellek sonucu gösteriliyor ({remain} sn).",
                    kind="idle",
                )
            self._on_check_result(
                self._last_check_result,
                silent_if_latest=silent_if_latest,
                silent_errors=silent_errors,
                present_in_center=present_in_center,
                prompt_on_available=prompt_on_available,
            )
            return

        if present_in_center:
            self._ensure_center_dialog()
            if self._center_dialog is not None:
                self._center_dialog.set_status("Güncellemeler denetleniyor...", kind="busy")
                self._center_dialog.set_check_enabled(False)
                self._center_dialog.set_install_enabled(False)
                self._center_dialog.set_progress_visible(False)

        self._check_worker = SyncWorker(check_for_updates, parent=self._parent)

        def on_done(res: Result) -> None:
            if isinstance(res, Result):
                self._last_check_result = res
                self._last_check_ts = time.monotonic()
                retry_after = self._result_retry_after_sec(res)
                if retry_after > 0:
                    self._check_blocked_until_ts = max(
                        self._check_blocked_until_ts,
                        self._last_check_ts + float(retry_after),
                    )
            self._on_check_result(
                res,
                silent_if_latest=silent_if_latest,
                silent_errors=silent_errors,
                present_in_center=present_in_center,
                prompt_on_available=prompt_on_available,
            )

        def on_finished() -> None:
            setattr(self, "_check_worker", None)
            if present_in_center and self._center_dialog is not None:
                self._center_dialog.set_check_enabled(True)

        self._check_worker.result_ready.connect(on_done)
        self._check_worker.finished.connect(on_finished)
        self._check_worker.start()

    def _on_check_result(
        self,
        result: Result,
        *,
        silent_if_latest: bool,
        silent_errors: bool,
        present_in_center: bool,
        prompt_on_available: bool,
    ) -> None:
        if present_in_center:
            self._apply_result_to_center(result)

        if not isinstance(result, Result):
            if not silent_errors:
                MessageHandler.show(self._parent, Result.fail("Güncelleme kontrol sonucu okunamadı."), only_errors=True)
            return

        if not result.success:
            data = result.data if isinstance(result.data, dict) else {}
            if present_in_center and bool(data.get("rate_limited")):
                # Center UI already shows detailed rate-limit state.
                return
            if not silent_errors:
                MessageHandler.show(self._parent, result, only_errors=True)
            return

        data = result.data or {}
        available = bool(data.get("available", False))
        if not available:
            if not silent_if_latest and not present_in_center:
                current = str(data.get("current_version") or "-")
                AppMessageCenter.info(self._parent, "Güncelleme", f"Yeni sürüm yok. Mevcut sürüm: {current}")
            return

        if not prompt_on_available:
            return

        release = data.get("release") or {}
        asset = data.get("selected_asset") or {}
        current = str(data.get("current_version") or "-")
        latest = str(data.get("latest_version") or "-")
        title = str(release.get("name") or release.get("tag_name") or f"v{latest}")
        notes = str(release.get("body") or "").strip()
        if len(notes) > 600:
            notes = notes[:600].rstrip() + "\n..."

        text = (
            f"Yeni sürüm bulundu.\n\n"
            f"Mevcut: v{current}\n"
            f"Yeni: v{latest}\n"
            f"Yayın: {title}\n\n"
            f"Güncellemeyi şimdi yüklemek ister misin?"
        )
        if notes:
            text = f"{text}\n\nNotlar:\n{notes}"

        answer = AppMessageCenter.confirm(
            self._parent,
            UPDATE_READY_DIALOG_TITLE,
            text,
            default_yes=True,
        )
        if not answer:
            return

        self._start_download(release=release, asset=asset, in_center=False)

    def _apply_result_to_center(self, result: Result) -> None:
        dialog = self._ensure_center_dialog()

        if not isinstance(result, Result):
            dialog.set_status("Kontrol sonucu okunamadı.", kind="error")
            dialog.set_notes("Güncelleme kontrolü geçersiz bir sonuç döndürdü.")
            dialog.set_install_enabled(False)
            self._pending_release = {}
            self._pending_asset = {}
            return

        if not result.success:
            data = result.data if isinstance(result.data, dict) else {}
            if bool(data.get("rate_limited")):
                retry_after = self._safe_int(data.get("retry_after_sec", 0), 0)
                if retry_after > 0:
                    dialog.set_status(f"Hız limiti ({retry_after} sn)", kind="error")
                    dialog.set_notes(
                        "GitHub API bu istemciyi geçici olarak yavaşlattı.\n"
                        f"Lütfen {retry_after} saniye sonra tekrar dene."
                    )
                else:
                    dialog.set_status("Hız limiti", kind="error")
                    dialog.set_notes(str(result.message or "GitHub API hız limiti algılandı."))
            else:
                dialog.set_status("Kontrol hatası", kind="error")
                dialog.set_notes(str(result.message or "Güncelleme kontrolü sırasında hata oluştu."))
            dialog.set_install_enabled(False)
            self._pending_release = {}
            self._pending_asset = {}
            return

        data = result.data or {}
        release = data.get("release") or {}
        asset = data.get("selected_asset") or {}
        available = bool(data.get("available", False))

        current = str(data.get("current_version") or APP_VERSION or "-")
        latest = str(data.get("latest_version") or current or "-")
        release_title = str(release.get("name") or release.get("tag_name") or f"v{latest}")
        published = _format_iso_date(str(release.get("published_at") or ""))
        notes = str(release.get("body") or "").strip()

        cfg = load_update_config()
        github = cfg.get("github") if isinstance(cfg.get("github"), dict) else {}
        owner = str(github.get("owner") or "-").strip() or "-"
        repo = str(github.get("repo") or "-").strip() or "-"
        channel = str(data.get("channel") or cfg.get("channel") or "stable").strip().lower() or "stable"

        asset_name = str(asset.get("name") or "").strip()
        asset_size = _format_bytes(int(asset.get("size") or 0)) if asset_name else "-"
        asset_text = f"{asset_name} ({asset_size})" if asset_name else "-"
        digest = str(asset.get("digest") or "").strip()
        if digest:
            asset_text = f"{asset_text} | {digest}"

        dialog.set_versions(current_version=current, latest_version=latest)
        dialog.set_release_meta(title=release_title, published_at=published)
        dialog.set_asset_meta(asset_text=asset_text, source_text=f"{owner}/{repo}")
        if is_runtime_updatable():
            runtime_text = f"Otomatik kurulum: Bu cihazda destekleniyor. Kanal: {channel}"
        else:
            runtime_text = f"Otomatik kurulum: Bu ortamda devre dışı (paket hazırlanır). Kanal: {channel}"
        dialog.set_runtime_text(runtime_text)
        dialog.set_notes(notes or "Yayın notu bulunamadı.")

        if available and asset_name:
            dialog.set_status("Yeni sürüm bulundu, yüklemeye hazır.", kind="update")
            dialog.set_install_enabled(True)
            self._pending_release = dict(release or {})
            self._pending_asset = dict(asset or {})
        else:
            dialog.set_status("Uygulama güncel sürümde.", kind="ok")
            dialog.set_install_enabled(False)
            self._pending_release = {}
            self._pending_asset = {}

    def _start_download_from_center(self) -> None:
        if self._download_worker is not None and self._download_worker.isRunning():
            if self._center_dialog is not None:
                self._center_dialog.set_status("İndirme zaten devam ediyor.", kind="busy")
            return
        if not self._pending_release or not self._pending_asset:
            if self._center_dialog is not None:
                self._center_dialog.set_status("Önce güncelleme denetimi yap.", kind="error")
            return
        self._start_download(release=self._pending_release, asset=self._pending_asset, in_center=True)

    def _start_download(self, *, release: dict, asset: dict, in_center: bool) -> None:
        if not isinstance(asset, dict) or not str(asset.get("download_url") or "").strip():
            MessageHandler.show(self._parent, Result.fail("Güncelleme paketi bilgisi eksik."), only_errors=True)
            return

        self._download_in_center = bool(in_center and self._center_dialog is not None)
        if self._download_in_center and self._center_dialog is not None:
            self._center_dialog.set_status("Güncelleme paketi hazırlanıyor...", kind="busy")
            self._center_dialog.set_progress_visible(True)
            self._center_dialog.set_progress(percent=0, stage_text=UPDATE_STATUS_PREPARING_TEXT)
            self._center_dialog.set_check_enabled(False)
            self._center_dialog.set_install_enabled(False)
        else:
            self._progress_dialog = UpdateProgressDialog(self._parent)
            self._progress_dialog.set_title("Güncelleme indiriliyor")
            self._progress_dialog.set_stage(UPDATE_STATUS_PREPARING_TEXT)
            self._progress_dialog.set_progress(0)
            self._progress_dialog.show()

        self._download_worker = _UpdateDownloadWorker(release=release, asset=asset, parent=self._parent)
        self._download_worker.progress_changed.connect(self._on_download_progress)
        self._download_worker.result_ready.connect(self._on_download_finished)
        self._download_worker.finished.connect(self._on_download_worker_finished)
        self._download_worker.start()

    def _on_download_worker_finished(self) -> None:
        self._download_worker = None
        if self._download_in_center and self._center_dialog is not None:
            self._center_dialog.set_check_enabled(True)
        self._download_in_center = False

    def _on_download_progress(self, percent: int, stage_text: str) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.set_stage(stage_text)
            self._progress_dialog.set_progress(percent)
        if self._center_dialog is not None:
            self._center_dialog.set_progress_visible(True)
            self._center_dialog.set_progress(percent=percent, stage_text=stage_text)

    def _on_download_finished(self, result: Result) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.set_progress(100)
            self._progress_dialog.close()
            self._progress_dialog = None

        if self._center_dialog is not None:
            self._center_dialog.set_progress(percent=100, stage_text=UPDATE_STATUS_COMPLETED_TEXT)

        if not isinstance(result, Result) or not result.success:
            bad = result if isinstance(result, Result) else Result.fail("Güncelleme indirme işlemi başarısız.")
            if self._center_dialog is not None:
                self._center_dialog.set_status("İndirme başarısız.", kind="error")
                self._center_dialog.set_notes(str(bad.message or "Güncelleme dosyası indirilemedi."))
                self._center_dialog.set_install_enabled(bool(self._pending_asset))
            MessageHandler.show(self._parent, bad, only_errors=True)
            return

        plan = (result.data or {}).get("plan") or {}
        if not is_runtime_updatable():
            workspace = str(plan.get("workspace") or "")
            if self._center_dialog is not None:
                self._center_dialog.set_status("Paket indirildi (manuel kurulum).", kind="ok")
                self._center_dialog.set_notes(
                    "Bu ortamda otomatik uygulama kapalı.\n"
                    f"İndirilen paket konumu:\n{workspace}"
                )
                self._center_dialog.set_install_enabled(False)
            AppMessageCenter.info(
                self._parent,
                UPDATE_READY_DIALOG_TITLE,
                "Güncelleme paketi indirildi. Bu ortamda otomatik uygulama devre dışı.\n"
                f"Dosya konumu: {workspace}",
            )
            return

        if self._center_dialog is not None:
            self._center_dialog.set_status("Kurulum başlatılmaya hazır.", kind="ok")
            self._center_dialog.set_install_enabled(False)

        AppMessageCenter.info(
            self._parent,
            UPDATE_LAUNCHED_DIALOG_TITLE,
            "Güncelleme paketi hazır. Tamam'a bastığında uygulama kapanacak ve kurulum penceresi açılacak.",
        )

        apply_res = launch_prepared_update(plan)
        if not apply_res.success:
            if self._center_dialog is not None:
                self._center_dialog.set_status("Kurulum baslatilamadi.", kind="error")
                self._center_dialog.set_install_enabled(True)
            MessageHandler.show(self._parent, apply_res, only_errors=True)
            return

        if self._center_dialog is not None:
            self._center_dialog.set_status("Güncelleme kurulumu başlatıldı.", kind="ok")
            self._center_dialog.set_install_enabled(False)

        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(350, app.quit)
