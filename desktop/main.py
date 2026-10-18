# main.py
from __future__ import annotations

import os
import sys

BOOTSTRAP_LOADING_DIALOG_DELAY_MS = 500


class _BootstrapWorkerPayload(tuple):
    __slots__ = ()

    @property
    def success(self) -> bool:
        return bool(self[0]) if len(self) > 0 else False

    @property
    def message(self) -> str:
        return str(self[1]) if len(self) > 1 else ""


def _run_orders_db_save_worker_mode() -> None:
    """
    Aynı EXE içerisinden ayrı process worker mode.
    GUI açılmaz. stdin'den JSON alır, stdout'a JSON basar.
    """
    from Orders.processors.trendyol.db_save_worker import main as worker_main

    worker_main()


def _run_listing_db_save_worker_mode() -> None:
    """
    Listing db save worker mode.
    """
    from Listing.processors.trendyol.db_save_worker import main as worker_main

    worker_main()


def _run_update_runner_mode(payload_path: str) -> None:
    from Update.views.runner_app import run_update_runner

    run_update_runner(payload_path)


def _process_qt_events_for(app, milliseconds: int) -> None:
    from PyQt6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < max(1, int(milliseconds or 1)):
        app.processEvents()


def _run_stock_dialog_smoke_mode(report_path: str = "") -> None:
    import json
    from pathlib import Path

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from Core.db.bootstrap import init_database
    from Stock.views.tab import StockTab

    app = QApplication.instance() or QApplication([sys.argv[0], "--smoke-stock-dialogs"])
    init_database()
    tab = StockTab()
    tab.show()
    _process_qt_events_for(app, 200)

    checks: list[dict[str, object]] = []
    errors: list[str] = []
    actions = (
        ("open_overview", 1200),
        ("open_items", 3000),
        ("open_tx", 1800),
        ("open_warehouses", 1200),
        ("open_upper_groups", 1200),
        ("open_sub_groups", 1200),
    )

    for method_name, wait_ms in actions:
        try:
            before = len(getattr(tab, "_open_dialogs", []))
            getattr(tab, method_name)()
            _process_qt_events_for(app, wait_ms)
            opened = len(getattr(tab, "_open_dialogs", [])) > before
            checks.append({"action": method_name, "opened": opened})
            if not opened:
                errors.append(f"{method_name}: dialog did not stay open")
        except Exception as exc:
            errors.append(f"{method_name}: {type(exc).__name__}: {exc}")
        finally:
            for dialog in list(getattr(tab, "_open_dialogs", [])):
                try:
                    dialog.close()
                except Exception:
                    pass
            _process_qt_events_for(app, 500)

    payload = {
        "success": not errors,
        "checks": checks,
        "errors": errors,
    }
    if report_path:
        Path(report_path).expanduser().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if errors:
        raise SystemExit(1)


def _run_worker_mode(identifier: str) -> None:
    normalized = (identifier or "").strip().replace("\\", "/").lower()

    worker_map = {
        "orders/processors/trendyol/db_save_worker.py": _run_orders_db_save_worker_mode,
        "listing/processors/trendyol/db_save_worker.py": _run_listing_db_save_worker_mode,
    }

    runner = worker_map.get(normalized)
    if runner is None:
        raise SystemExit(f"Unknown worker identifier: {identifier}")

    runner()


def _cli_router() -> bool:
    """
    True dönerse program GUI açmadan çıkacak demektir.
    """
    if "--worker" in sys.argv:
        idx = sys.argv.index("--worker")
        if idx + 1 >= len(sys.argv):
            raise SystemExit("--worker requires an identifier")
        _run_worker_mode(sys.argv[idx + 1])
        return True

    if "--update-runner" in sys.argv:
        idx = sys.argv.index("--update-runner")
        if idx + 1 >= len(sys.argv):
            raise SystemExit("--update-runner requires a payload path")
        _run_update_runner_mode(sys.argv[idx + 1])
        return True

    if "--smoke-stock-dialogs" in sys.argv:
        idx = sys.argv.index("--smoke-stock-dialogs")
        report_path = ""
        if idx + 1 < len(sys.argv) and not str(sys.argv[idx + 1]).startswith("--"):
            report_path = sys.argv[idx + 1]
        _run_stock_dialog_smoke_mode(report_path)
        return True

    return False


def _apply_runtime_flags() -> None:
    """
    GUI runtime bayrakları.
    - --test-lab-ui 1|0
    - --enable-test-lab-ui
    - --disable-test-lab-ui
    """
    if "--test-lab-ui" in sys.argv:
        idx = sys.argv.index("--test-lab-ui")
        if idx + 1 >= len(sys.argv):
            raise SystemExit("--test-lab-ui requires 1 or 0")

        raw = str(sys.argv[idx + 1]).strip().lower()
        if raw in {"1", "true", "on", "yes", "enable", "enabled"}:
            os.environ["ENABLE_TEST_LAB_UI"] = "1"
        elif raw in {"0", "false", "off", "no", "disable", "disabled"}:
            os.environ["ENABLE_TEST_LAB_UI"] = "0"
        else:
            raise SystemExit("--test-lab-ui accepts only 1/0 (or true/false variants)")

        del sys.argv[idx : idx + 2]

    if "--enable-test-lab-ui" in sys.argv:
        os.environ["ENABLE_TEST_LAB_UI"] = "1"
        sys.argv.remove("--enable-test-lab-ui")

    if "--disable-test-lab-ui" in sys.argv:
        os.environ["ENABLE_TEST_LAB_UI"] = "0"
        sys.argv.remove("--disable-test-lab-ui")


def _use_pre_shell_bootstrap() -> bool:
    raw = os.getenv("ORDER_SCOUT_PRE_SHELL_BOOTSTRAP", "").strip().lower()
    if raw in {"1", "true", "on", "yes"}:
        return True
    if raw in {"0", "false", "off", "no"}:
        return False
    return bool(getattr(sys, "frozen", False))


def _run_bootstrap_with_loading(app) -> _BootstrapWorkerPayload:
    from PyQt6.QtCore import QEventLoop, QThread, QTimer, Qt, pyqtSignal
    from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

    class _BootstrapWorker(QThread):
        result_ready = pyqtSignal(object)

        def run(self) -> None:
            try:
                from Core.db.bootstrap import init_database

                init_database()
                self.result_ready.emit(_BootstrapWorkerPayload((True, "")))
            except Exception as exc:
                self.result_ready.emit(_BootstrapWorkerPayload((False, str(exc))))

    class _BootstrapDialog(QDialog):
        def __init__(self) -> None:
            super().__init__(None)
            self.setWindowTitle("OrderScout")
            self.setWindowFlags(
                Qt.WindowType.Dialog
                | Qt.WindowType.CustomizeWindowHint
                | Qt.WindowType.WindowTitleHint
            )
            self.setModal(True)
            self.setMinimumWidth(420)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(20, 18, 20, 18)
            layout.setSpacing(10)

            title = QLabel("Veritabanı hazırlanıyor...")
            title.setStyleSheet("font-size: 18px; font-weight: 700;")
            subtitle = QLabel("Migration ve başlangıç kontrolleri arka planda çalışıyor.")
            subtitle.setWordWrap(True)
            subtitle.setStyleSheet("color: #475569;")
            progress = QProgressBar(self)
            progress.setRange(0, 0)
            progress.setTextVisible(False)

            layout.addWidget(title)
            layout.addWidget(subtitle)
            layout.addWidget(progress)

    dialog = _BootstrapDialog()
    worker = _BootstrapWorker(dialog)
    loop = QEventLoop()
    show_timer = QTimer(dialog)
    show_timer.setSingleShot(True)
    show_timer.setInterval(BOOTSTRAP_LOADING_DIALOG_DELAY_MS)
    result_holder: dict[str, _BootstrapWorkerPayload] = {}

    def _on_result(payload: object) -> None:
        result = payload if isinstance(payload, _BootstrapWorkerPayload) else _BootstrapWorkerPayload((False, "Bootstrap başarısız oldu."))
        result_holder["payload"] = result
        show_timer.stop()
        if dialog.isVisible():
            dialog.close()
        loop.quit()

    def _show_if_still_running() -> None:
        if "payload" in result_holder:
            return
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    worker.result_ready.connect(_on_result)
    show_timer.timeout.connect(_show_if_still_running)
    worker.start()
    show_timer.start()
    loop.exec()
    worker.wait()
    app.processEvents()
    return result_holder.get("payload", _BootstrapWorkerPayload((False, "Bootstrap sonucu alınamadı.")))


def _start_bootstrap_with_loading(app, parent, finished_callback):
    from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
    from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

    class _BootstrapWorker(QThread):
        result_ready = pyqtSignal(object)

        def run(self) -> None:
            try:
                from Core.db.bootstrap import init_database

                init_database()
                self.result_ready.emit(_BootstrapWorkerPayload((True, "")))
            except Exception as exc:
                self.result_ready.emit(_BootstrapWorkerPayload((False, str(exc))))

    class _BootstrapDialog(QDialog):
        def __init__(self) -> None:
            super().__init__(parent)
            self.setWindowTitle("OrderScout")
            self.setWindowFlags(
                Qt.WindowType.Dialog
                | Qt.WindowType.CustomizeWindowHint
                | Qt.WindowType.WindowTitleHint
            )
            self.setModal(True)
            self.setMinimumWidth(420)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(20, 18, 20, 18)
            layout.setSpacing(10)

            title = QLabel("Veritabanı hazırlanıyor...")
            title.setStyleSheet("font-size: 18px; font-weight: 700;")
            subtitle = QLabel("Migration ve başlangıç kontrolleri arka planda çalışıyor.")
            subtitle.setWordWrap(True)
            subtitle.setStyleSheet("color: #475569;")
            progress = QProgressBar(self)
            progress.setRange(0, 0)
            progress.setTextVisible(False)

            layout.addWidget(title)
            layout.addWidget(subtitle)
            layout.addWidget(progress)

    dialog = _BootstrapDialog()
    worker = _BootstrapWorker(parent)
    show_timer = QTimer(parent)
    show_timer.setSingleShot(True)
    show_timer.setInterval(BOOTSTRAP_LOADING_DIALOG_DELAY_MS)
    result_holder: dict[str, _BootstrapWorkerPayload] = {}

    def _on_result(payload: object) -> None:
        result = payload if isinstance(payload, _BootstrapWorkerPayload) else _BootstrapWorkerPayload((False, "Bootstrap başarısız oldu."))
        result_holder["payload"] = result
        show_timer.stop()
        if dialog.isVisible():
            dialog.close()
        finished_callback(result)

    def _show_if_still_running() -> None:
        if "payload" in result_holder:
            return
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _cleanup_worker() -> None:
        worker.deleteLater()
        dialog.deleteLater()

    worker.result_ready.connect(_on_result)
    worker.finished.connect(_cleanup_worker)
    show_timer.timeout.connect(_show_if_still_running)
    worker.start()
    show_timer.start()
    app.processEvents()
    return {
        "worker": worker,
        "dialog": dialog,
        "show_timer": show_timer,
        "result_holder": result_holder,
    }


def build_source_app_ai_acceptance_surface(app):
    """Build the real main.py-owned application shell and return its AI tab.

    Background bootstrap/update scheduling stays with the caller, but the UI
    composition follows the production MainInterface and lazy-tab path.
    """
    from Main_interface.views import MainInterface

    window = MainInterface(defer_startup=True, show_ai_ui=True)
    window.showMaximized()
    window._activate_ai_tab()
    host = window._tab_hosts.get("ai")
    if host is None:
        window.close()
        raise RuntimeError("MainInterface AI tab host bulunamadi.")
    host.request_load()
    elapsed_ms = 0
    while host.content is None and elapsed_ms < 15_000:
        _process_qt_events_for(app, 25)
        elapsed_ms += 25
    if host.content is None:
        window.close()
        raise RuntimeError("MainInterface AI tab source UI icinde yuklenemedi.")
    return window, host.content


def main() -> int:
    _apply_runtime_flags()

    # 1) CLI router (GUI öncesi!)
    if _cli_router():
        return 0

    # 2) GUI shell first, DB bootstrap in the background
    from PyQt6.QtWidgets import QApplication
    from Main_interface.views import MainInterface

    app = QApplication(sys.argv)
    if _use_pre_shell_bootstrap():
        from Core.views.messaging import AppMessageCenter

        bootstrap_result = _run_bootstrap_with_loading(app)
        if not bootstrap_result.success:
            AppMessageCenter.error(
                None,
                "OrderScout",
                bootstrap_result.message or "Veritabanı başlatılamadı.",
            )
            return 1

        window = MainInterface()
        window.showMaximized()
        return app.exec()

    window = MainInterface(defer_startup=True)
    window.showMaximized()

    def _on_bootstrap_finished(bootstrap_result: _BootstrapWorkerPayload) -> None:
        if not bootstrap_result.success:
            from Core.views.messaging import AppMessageCenter

            AppMessageCenter.error(
                window,
                "OrderScout",
                bootstrap_result.message or "Veritabanı başlatılamadı.",
            )
            app.quit()
            return
        window.start_deferred_work()

    window._bootstrap_handle = _start_bootstrap_with_loading(
        app,
        window,
        _on_bootstrap_finished,
    )
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
