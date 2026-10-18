from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from Core.threads.sync_worker import SyncWorker
from Core.views import BadgeButton, QuickAccessSection, RECORD_WORKSPACE_STYLE as FINANCE_STYLE
from Core.views.tab_widgets import DashboardHeroCard
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from Logistics.constants.ui_constants import (
    LOGISTICS_CARGO_PROVIDERS_BUTTON_TEXT,
    LOGISTICS_CARGO_TARIFFS_BUTTON_TEXT,
    LOGISTICS_QUICK_ACCESS_SUBTITLE,
    LOGISTICS_QUICK_ACCESS_TITLE,
    LOGISTICS_SUMMARY_LOADED_TEXT,
    LOGISTICS_TAB_SUBTITLE,
    LOGISTICS_TAB_TITLE,
)
from Logistics.signals.signals import logistics_signals
from settings import ASSETS_DIR

if TYPE_CHECKING:
    from Logistics.views.cargo_providers_window import LogisticsCargoProvidersFormWindow
    from Logistics.views.cargo_tariffs_window import LogisticsCargoTariffsWindow

# from Logistics.views.cargo_providers_window import LogisticsCargoProvidersFormWindow
# from Logistics.views.cargo_tariffs_window import LogisticsCargoTariffsWindow

# Backward compatibility for older imports.
LogisticsCargoProvidersWindow = None

_LOGISTICS_SUMMARY_BOOTSTRAP_DELAY_MS = 350


def _load_logistics_summary_state() -> Result:
    from Logistics.views.actions import (
        load_logistics_cargo_providers,
        load_logistics_cargo_tariffs,
    )

    providers_result = load_logistics_cargo_providers(source_filter="pending")
    tariffs_result = load_logistics_cargo_tariffs(source_state="pending")
    return Result.ok(
        LOGISTICS_SUMMARY_LOADED_TEXT,
        close_dialog=False,
        data={
            "providers_result": providers_result,
            "tariffs_result": tariffs_result,
        },
    )


class LogisticsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("FinanceRoot")
        self.setStyleSheet(FINANCE_STYLE)

        self.cargo_providers_window = None
        self.cargo_tariffs_window = None
        self._summary_bootstrapped = False
        self._summary_refresh_pending = False
        self._summary_worker: SyncWorker | None = None
        self._quick_badges = {
            "providers": 0,
            "tariffs": 0,
        }
        self._pending_current_counts = {
            "providers": 0,
            "tariffs": 0,
        }
        self._pending_seen_counts = {
            "providers": 0,
            "tariffs": 0,
        }
        self._summary_bootstrap_timer = QTimer(self)
        self._summary_bootstrap_timer.setSingleShot(True)
        self._summary_bootstrap_timer.timeout.connect(self._refresh_summaries_async)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        hero = DashboardHeroCard(
            title=LOGISTICS_TAB_TITLE,
            subtitle=LOGISTICS_TAB_SUBTITLE,
        )
        root.addWidget(hero)

        content_card = QuickAccessSection(
            title=LOGISTICS_QUICK_ACCESS_TITLE,
            subtitle=LOGISTICS_QUICK_ACCESS_SUBTITLE,
            parent=self,
        )
        content_layout = content_card.body_layout

        self.cargo_providers_btn = BadgeButton(
            LOGISTICS_CARGO_PROVIDERS_BUTTON_TEXT,
            icon_path=os.path.join(ASSETS_DIR, "logistics-cargo-providers-icon.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.cargo_providers_btn.setMinimumHeight(100)
        self.cargo_providers_btn.clicked.connect(self.open_cargo_providers_window)
        self.cargo_tariffs_btn = BadgeButton(
            LOGISTICS_CARGO_TARIFFS_BUTTON_TEXT,
            icon_path=os.path.join(ASSETS_DIR, "logistics-cargo-tariffs-icon.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.cargo_tariffs_btn.setMinimumHeight(100)
        self.cargo_tariffs_btn.clicked.connect(self.open_cargo_tariffs_window)
        quick_btn_row = QHBoxLayout()
        quick_btn_row.setContentsMargins(0, 0, 0, 0)
        quick_btn_row.setSpacing(12)
        quick_btn_row.addWidget(self.cargo_providers_btn)
        quick_btn_row.addWidget(self.cargo_tariffs_btn)
        quick_btn_row.addStretch(1)
        content_layout.addLayout(quick_btn_row)

        content_layout.addStretch(1)
        root.addWidget(content_card, 1)
        logistics_signals.cargo_providers_changed.connect(self._on_cargo_providers_changed)
        logistics_signals.cargo_tariffs_changed.connect(self._on_cargo_tariffs_changed)
        self._apply_quick_access_badges()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._summary_bootstrapped:
            return
        self._summary_bootstrapped = True
        self._summary_bootstrap_timer.start(_LOGISTICS_SUMMARY_BOOTSTRAP_DELAY_MS)

    def closeEvent(self, event) -> None:
        self._summary_bootstrap_timer.stop()
        worker = self._summary_worker
        if worker is not None and worker.isRunning():
            worker.quit()
            worker.wait(1500)
        super().closeEvent(event)

    def _refresh_summaries_async(self) -> None:
        worker = self._summary_worker
        if worker is not None and worker.isRunning():
            self._summary_refresh_pending = True
            return

        self._summary_refresh_pending = False

        worker = SyncWorker(_load_logistics_summary_state, parent=self)
        self._summary_worker = worker
        worker.result_ready.connect(self._on_summary_result)
        worker.finished.connect(self._on_summary_finished)
        worker.start()

    def _on_summary_result(self, result: Result) -> None:
        payload = dict((result.data or {})) if getattr(result, "success", False) else {}
        providers_result = payload.get("providers_result")
        tariffs_result = payload.get("tariffs_result")
        self._apply_cargo_providers_summary(providers_result)
        self._apply_cargo_tariffs_summary(tariffs_result)

    def _on_summary_finished(self) -> None:
        worker = self._summary_worker
        if worker is not None:
            worker.deleteLater()
        self._summary_worker = None
        if self._summary_refresh_pending:
            self._summary_refresh_pending = False
            QTimer.singleShot(0, self._refresh_summaries_async)

    def _apply_cargo_providers_summary(self, result) -> None:
        records = (getattr(result, "data", None) or {}).get("records") or []
        count = len(records) if getattr(result, "success", False) else 0
        self._sync_pending_quick_badge("providers", count)

    def _apply_cargo_tariffs_summary(self, result) -> None:
        records = (getattr(result, "data", None) or {}).get("records") or []
        count = len(records) if getattr(result, "success", False) else 0
        self._sync_pending_quick_badge("tariffs", count)

    def _apply_quick_access_badges(self) -> None:
        self.cargo_providers_btn.setBadgeCount(int(self._quick_badges.get("providers", 0)))
        self.cargo_providers_btn.setActive(True)
        self.cargo_tariffs_btn.setBadgeCount(int(self._quick_badges.get("tariffs", 0)))
        self.cargo_tariffs_btn.setActive(True)

    def _clear_quick_badge(self, key: str) -> None:
        if key not in self._quick_badges:
            return
        if key in self._pending_seen_counts:
            self._pending_seen_counts[key] = max(0, int(self._pending_current_counts.get(key, 0)))
        self._quick_badges[key] = 0
        self._apply_quick_access_badges()

    def _sync_pending_quick_badge(self, key: str, pending_count: int) -> None:
        if key not in self._quick_badges or key not in self._pending_current_counts:
            return
        current = max(0, int(pending_count or 0))
        self._pending_current_counts[key] = current
        if self._is_quick_target_visible(key):
            self._pending_seen_counts[key] = current
            self._quick_badges[key] = 0
        else:
            seen = min(max(0, int(self._pending_seen_counts.get(key, 0))), current)
            self._pending_seen_counts[key] = seen
            self._quick_badges[key] = max(0, current - seen)
        self._apply_quick_access_badges()

    def _is_quick_target_visible(self, key: str) -> bool:
        if key == "providers":
            return bool(self.cargo_providers_window is not None and self.cargo_providers_window.isVisible())
        if key == "tariffs":
            return bool(self.cargo_tariffs_window is not None and self.cargo_tariffs_window.isVisible())
        return False

    def _on_cargo_providers_changed(self) -> None:
        self._summary_bootstrap_timer.start(0)

    def _on_cargo_tariffs_changed(self) -> None:
        self._summary_bootstrap_timer.start(0)

    def open_cargo_providers_window(self) -> None:
        try:
            from Logistics.views.cargo_providers_window import LogisticsCargoProvidersFormWindow

            created_now = self.cargo_providers_window is None
            if self.cargo_providers_window is None:
                self.cargo_providers_window = LogisticsCargoProvidersFormWindow()
                self.cargo_providers_window.itemsChanged.connect(self._refresh_summaries_async)
            self._clear_quick_badge("providers")
            self.cargo_providers_window.showMaximized()
            self.cargo_providers_window.raise_()
            self.cargo_providers_window.activateWindow()
            if not created_now:
                self.cargo_providers_window.request_reload_items()
        except Exception as exc:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(exc), error=exc, close_dialog=False),
                only_errors=True,
            )

    def open_cargo_tariffs_window(self) -> None:
        try:
            from Logistics.views.cargo_tariffs_window import LogisticsCargoTariffsWindow

            created_now = False
            if self.cargo_tariffs_window is None:
                self.cargo_tariffs_window = LogisticsCargoTariffsWindow()
                self.cargo_tariffs_window.itemsChanged.connect(self._refresh_summaries_async)
                created_now = True
            self._clear_quick_badge("tariffs")
            self.cargo_tariffs_window.showMaximized()
            self.cargo_tariffs_window.raise_()
            self.cargo_tariffs_window.activateWindow()
            if not created_now:
                self.cargo_tariffs_window.request_reload_items()
        except Exception as exc:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(exc), error=exc, close_dialog=False),
                only_errors=True,
            )


_WINDOW_EXPORTS = {
    "LogisticsCargoProvidersFormWindow": (".cargo_providers_window", "LogisticsCargoProvidersFormWindow"),
    "LogisticsCargoProvidersWindow": (".cargo_providers_window", "LogisticsCargoProvidersFormWindow"),
    "LogisticsCargoTariffsWindow": (".cargo_tariffs_window", "LogisticsCargoTariffsWindow"),
}


def __getattr__(name: str):
    target = _WINDOW_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module_name, attr_name = target
    value = getattr(import_module(module_name, __package__), attr_name)
    globals()[name] = value
    if name == "LogisticsCargoProvidersWindow":
        globals()["LogisticsCargoProvidersWindow"] = value
    return value


__all__ = [
    "LogisticsCargoProvidersFormWindow",
    "LogisticsCargoProvidersWindow",
    "LogisticsCargoTariffsWindow",
    "LogisticsTab",
]
