from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QListWidget

from Account.signals.signals import account_signals
from Core.threads.sync_worker import SyncWorker
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message


class CompanyListWidget(QListWidget):
    companies_loaded = pyqtSignal(int)
    loading_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._reload_worker: SyncWorker | None = None
        self._reload_seq = 0
        self._has_loaded_once = False
        account_signals.company_changed.connect(self.reload_companies)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._has_loaded_once and self._reload_worker is None:
            self.reload_companies()

    def closeEvent(self, event):
        worker = self._reload_worker
        if worker is not None:
            try:
                worker.result_ready.disconnect()
            except Exception:
                pass
            try:
                worker.finished.disconnect()
            except Exception:
                pass
            self._reload_worker = None
        super().closeEvent(event)

    def reload_companies(self):
        if self._reload_worker is not None and self._reload_worker.isRunning():
            return
        from Account.processors.pipeline import get_active_companies

        self._reload_seq += 1
        seq = int(self._reload_seq)
        selected_pks = set(self.get_selected_company_pks()) if self.count() > 0 else None
        worker = SyncWorker(get_active_companies, parent=self)
        self._reload_worker = worker
        self.loading_changed.emit(True)

        def _after(result: Result) -> None:
            if seq != self._reload_seq:
                return
            self._has_loaded_once = True
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self.companies_loaded.emit(self.count())
                return
            self._safe_build(result, selected_pks=selected_pks)

        def _finished() -> None:
            if self._reload_worker is worker:
                self._reload_worker = None
            if seq == self._reload_seq:
                self.loading_changed.emit(False)
            worker.deleteLater()

        worker.result_ready.connect(_after)
        worker.finished.connect(_finished)
        worker.start()

    def _safe_build(self, result: Result, *, selected_pks: set[int] | None = None):
        updates_were_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        try:
            from Account.views.actions import build_company_list

            for i in range(self.count()):
                widget = self.itemWidget(self.item(i))
                if widget:
                    widget.deleteLater()
            self.clear()

            res = build_company_list(self, result)
            if not res.success:
                MessageHandler.show(self, res, only_errors=True)
                self.companies_loaded.emit(self.count())
                return

            if selected_pks is not None:
                for i in range(self.count()):
                    item = self.item(i)
                    widget = self.itemWidget(item)
                    if widget is None:
                        continue
                    button = getattr(widget, "right_widget", None)
                    if button is None:
                        continue
                    pk = item.data(Qt.ItemDataRole.UserRole)
                    button.setChecked(pk in selected_pks)
            self.companies_loaded.emit(self.count())
        except Exception as e:
            MessageHandler.show(self, Result.fail(map_error_to_message(e), error=e), only_errors=True)
            self.companies_loaded.emit(self.count())
        finally:
            self.setUpdatesEnabled(updates_were_enabled)
            self.viewport().update()

    def get_selected_company_pks(self) -> list[int]:
        selected: list[int] = []
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            if not widget:
                continue
            button = getattr(widget, "right_widget", None)
            if button and button.isChecked():
                pk = item.data(Qt.ItemDataRole.UserRole)
                if pk is not None:
                    selected.append(pk)
        return selected

    def select_all(self):
        for i in range(self.count()):
            widget = self.itemWidget(self.item(i))
            if widget and hasattr(widget, "right_widget") and not widget.right_widget.isChecked():
                widget.right_widget.setChecked(True)

    def deselect_all(self):
        for i in range(self.count()):
            widget = self.itemWidget(self.item(i))
            if widget and hasattr(widget, "right_widget") and widget.right_widget.isChecked():
                widget.right_widget.setChecked(False)
