from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from Core.services.business_refresh import business_refresh_signals
from Account.signals.signals import account_signals
from Core.threads.sync_worker import SyncWorker
from Core.views import (
    ActionPulseButton,
    BadgeButton,
    FlowLayout,
    QuickAccessSection,
    RECORD_WORKSPACE_STYLE as FINANCE_STYLE,
    RecordWorkspaceSplitShell,
)
from Core.views import RecordWorkspaceCardRecord as OrdersStyleCardRecord, RecordWorkspaceListWidget as OrdersStyleListWidget
from Core.views.tab_widgets import DashboardHeroCard
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from settings import (
    ASSETS_DIR,
    ENABLE_FINANCE_INVOICES_UI,
    ENABLE_FINANCE_TRANSACTIONS_UI,
)
from Stock.signals.signals import stock_signals

if TYPE_CHECKING:
    from Account.views.company_list_widget import CompanyListWidget
    from Logistics.views.cargo_tariffs_window import FinanceCargoTariffCard, FinanceCargoTariffsWindow
    from .finance_brand_manager_window import FinanceBrandManagerDialog
    from .finance_company_manager_window import FinanceCompanyManagerDialog
    from .finance_cost_items_window import FinanceCostItemCard, FinanceCostItemsWindow
    from .finance_manager_window import FinanceInvoiceCard, FinanceManagerWindow
    from .finance_transactions_window import FinanceTransactionWorkspaceRecord, FinanceTransactionsWindow


def _load_finance_summary_state() -> Result:
    from Finance.views.actions import action_list_brands, action_list_companies, load_finance_cost_items

    return Result.ok(
        "Finans özeti yüklendi.",
        close_dialog=False,
        data={
            "cost_items_result": load_finance_cost_items(source_state="pending"),
            "brands_result": action_list_brands(only_active=False),
            "companies_result": action_list_companies(only_active=False),
        },
    )


class FinanceTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("FinanceRoot")
        self.setStyleSheet(FINANCE_STYLE)

        self.cost_items_window = None
        self.invoices_window = None
        self.transactions_window = None
        self._brand_dialog = None
        self._company_dialog = None
        self._summary_worker: SyncWorker | None = None
        self._summary_refresh_pending = False
        self._left_stick_size = 520
        self._summary_bootstrapped = False
        self._quick_badges = {
            "cost_items": 0,
            "brands": 0,
            "companies": 0,
        }
        self._pending_current_counts = {
            "cost_items": 0,
        }
        self._pending_seen_counts = {
            "cost_items": 0,
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        hero = DashboardHeroCard(
            title="Finans",
            subtitle="Kayıtlar arka planda otomatik güncellenir.",
        )
        root.addWidget(hero)

        workspace_host = QWidget(self)
        root.addWidget(workspace_host, 1)

        self._workspace_shell = RecordWorkspaceSplitShell(
            workspace_host,
            sidebar_width=92,
            left_stick_size=self._left_stick_size,
            left_collapse_trigger=480,
            min_left_width=320,
            min_right_width=320,
            fallback_total_width=1540,
            root_margins=(0, 0, 0, 0),
            snap_on_drag=True,
        )
        self._workspace_shell.set_state_changed_callback(self._sync_sidebar_state_from_splitter)
        self._panel_sidebar = self._workspace_shell.sidebar
        self._panel_sidebar.add_panel_button(
            "fetch",
            "",
            tooltip="Otomatik güncelleme durumu",
            icon_path=str(ASSETS_DIR / "veri-cekme.png"),
            shape="circular",
            icon_scale=1.28,
        )
        self._panel_sidebar.panel_toggled.connect(self._on_panel_sidebar_toggled)
        splitter = self._workspace_shell.splitter
        self._tab_splitter = splitter

        panel_card = QFrame(self)
        panel_card.setObjectName("SectionCard")
        panel_layout = QVBoxLayout(panel_card)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(10)
        panel_layout.addWidget(QLabel("Otomatik Güncelleme", objectName="SectionTitle"))

        self.no_company_card = QFrame(self)
        self.no_company_card.setObjectName("QuickCard")
        no_company_layout = QVBoxLayout(self.no_company_card)
        no_company_layout.setContentsMargins(12, 10, 12, 10)
        no_company_layout.setSpacing(8)
        no_company_layout.addWidget(QLabel("Henüz şirket yok", objectName="SectionTitle"))
        self.no_company_hint = QLabel(
            "Finans verisi çekmeden önce en az bir şirket hesabı eklemelisin.",
            objectName="Muted",
        )
        self.no_company_hint.setWordWrap(True)
        self.btn_add_company = ActionPulseButton(text="Şirket Ekle", center_text=True)
        self.btn_add_company.setMinimumWidth(220)
        self.btn_add_company.setEnabled(True)
        self.btn_add_company.clicked.connect(self._open_company_manager_from_fetch_panel)
        no_company_layout.addWidget(self.no_company_hint)
        no_company_layout.addWidget(self.btn_add_company, alignment=Qt.AlignmentFlag.AlignLeft)
        panel_layout.addWidget(self.no_company_card)

        from Account.views.company_list_widget import CompanyListWidget

        self.company_list = CompanyListWidget()
        self.company_list.setMinimumWidth(260)
        self.company_list.companies_loaded.connect(lambda *_args: self._refresh_company_list_state())
        panel_layout.addWidget(self.company_list)

        self.status_label = QLabel("Otomatik güncelleme hazır.", objectName="Muted")
        self.status_label.setWordWrap(True)
        panel_layout.addWidget(self.status_label)
        panel_layout.addStretch(1)

        left_scroll = QScrollArea(self)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setWidget(panel_card)
        splitter.addWidget(left_scroll)

        placeholder_card = QuickAccessSection(
            title="Hızlı Erişim",
            subtitle="Maliyet kartları, markalar ve firmaları ayrı pencerede aç.",
            parent=self,
        )
        placeholder_layout = placeholder_card.body_layout

        self.cost_items_btn = BadgeButton(
            "Maliyet Kartları",
            icon_path=os.path.join(ASSETS_DIR, "finance-cost-items-icon.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.cost_items_btn.setMinimumHeight(100)
        self.cost_items_btn.clicked.connect(self.open_cost_items_window)

        self.invoices_btn = BadgeButton(
            "Faturalar",
            icon_path=os.path.join(ASSETS_DIR, "finance-invoices-icon.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.invoices_btn.setMinimumHeight(100)
        self.invoices_btn.setActive(True)
        self.invoices_btn.clicked.connect(self.open_invoices_window)

        self.transactions_btn = BadgeButton(
            "Hareketler",
            icon_path=os.path.join(ASSETS_DIR, "finance-transactions-icon.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.transactions_btn.setMinimumHeight(100)
        self.transactions_btn.setActive(True)
        self.transactions_btn.clicked.connect(self.open_transactions_window)

        self.brands_btn = BadgeButton(
            "Markalar",
            icon_path=os.path.join(ASSETS_DIR, "markalar.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.brands_btn.setMinimumHeight(100)
        self.brands_btn.clicked.connect(self.open_brand_manager_window)

        self.companies_btn = BadgeButton(
            "Firmalar",
            icon_path=os.path.join(ASSETS_DIR, "firmalar.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.companies_btn.setMinimumHeight(100)
        self.companies_btn.clicked.connect(self.open_company_manager_window)
        quick_btn_host = QWidget(self)
        quick_btn_row = FlowLayout(quick_btn_host, margin=0, spacing=12)
        quick_btn_row.addWidget(self.cost_items_btn)
        quick_btn_row.addWidget(self.invoices_btn)
        quick_btn_row.addWidget(self.transactions_btn)
        quick_btn_row.addWidget(self.brands_btn)
        quick_btn_row.addWidget(self.companies_btn)
        self.invoices_btn.setVisible(bool(ENABLE_FINANCE_INVOICES_UI))
        self.transactions_btn.setVisible(bool(ENABLE_FINANCE_TRANSACTIONS_UI))
        placeholder_layout.addWidget(quick_btn_host)

        placeholder_layout.addStretch(1)

        right_scroll = QScrollArea(self)
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setWidget(placeholder_card)
        splitter.addWidget(right_scroll)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        splitter.setSizes([520, 1020])

        self._sync_sidebar_state_from_splitter()
        account_signals.company_changed.connect(self._on_companies_changed)
        stock_signals.quick_access_changed.connect(self._on_stock_quick_access_changed)
        self._apply_quick_access_badges()
        business_refresh_signals.status_changed.connect(self._on_background_status)
        business_refresh_signals.refreshed.connect(self._on_background_refreshed)
        self.status_label.setText(business_refresh_signals.statuses.get("finance", "Otomatik güncelleme hazır."))

    def _refresh_company_list_state(self, *, reload_companies: bool = False):
        if reload_companies:
            self.company_list.reload_companies()
            return
        has_companies = self.company_list.count() > 0
        self.no_company_card.setVisible(not has_companies)
        self.company_list.setVisible(has_companies)
        for index in range(self.company_list.count()):
            widget = self.company_list.itemWidget(self.company_list.item(index))
            control = getattr(widget, "right_widget", None)
            if control is not None:
                control.hide()

    def _on_background_status(self, domain: str, message: str) -> None:
        if domain == "finance":
            self.status_label.setText(message)

    def _on_background_refreshed(self, domain: str, payload: object) -> None:
        if domain != "finance":
            return
        self._refresh_summary_async()
        for window in (self.invoices_window, self.transactions_window):
            if window is not None and window.isVisible():
                window.reload_from_db()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._summary_bootstrapped:
            return
        self._summary_bootstrapped = True
        QTimer.singleShot(0, self._bootstrap_summary_state)

    def _bootstrap_summary_state(self) -> None:
        self._refresh_summary_async()

    def closeEvent(self, event) -> None:
        worker = self._summary_worker
        if worker is not None and worker.isRunning():
            worker.quit()
            worker.wait(1500)
        super().closeEvent(event)

    def _is_fetch_panel_open(self) -> bool:
        return self._workspace_shell.is_left_panel_open()

    def _sync_sidebar_state_from_splitter(self) -> None:
        self._workspace_shell.sync_sidebar_active("fetch" if self._is_fetch_panel_open() else None)

    def _open_fetch_panel(self) -> None:
        self._workspace_shell.open_left_panel(left_width=self._left_stick_size, min_left=320, min_right=320)

    def _close_fetch_panel(self) -> None:
        self._workspace_shell.close_left_panel()

    def _on_panel_sidebar_toggled(self, panel_id: str, active: bool) -> None:
        if panel_id != "fetch":
            return
        if active:
            self._open_fetch_panel()
        else:
            self._close_fetch_panel()

    def _on_companies_changed(self) -> None:
        QTimer.singleShot(0, self._refresh_company_list_state)

    def _open_company_manager_from_fetch_panel(self) -> None:
        try:
            main_window = self.window()
            opener = getattr(main_window, "company_ui", None)
            if opener is not None and hasattr(opener, "open_comp_manage_dialog"):
                opener.open_comp_manage_dialog()
            else:
                from Account.views.views import CompanyManagerDialog

                dialog = CompanyManagerDialog()
                dialog.exec()
        except Exception as exc:
            MessageHandler.show(self, Result.fail(map_error_to_message(exc), error=exc), only_errors=True)
        finally:
            self._refresh_company_list_state(reload_companies=True)


    def _refresh_cost_items_summary(self) -> None:
        from Finance.views.actions import load_finance_cost_items

        result = load_finance_cost_items(source_state="pending")
        self._apply_cost_items_summary(result)

    def _refresh_brand_summary(self) -> None:
        from Finance.views.actions import action_list_brands

        result = action_list_brands(only_active=False)
        self._apply_brand_summary(result)

    def _refresh_catalog_company_summary(self) -> None:
        from Finance.views.actions import action_list_companies

        result = action_list_companies(only_active=False)
        self._apply_catalog_company_summary(result)

    def _refresh_summary_async(self) -> None:
        worker = self._summary_worker
        if worker is not None and worker.isRunning():
            self._summary_refresh_pending = True
            return

        self._summary_refresh_pending = False
        worker = SyncWorker(_load_finance_summary_state, parent=self)
        self._summary_worker = worker
        worker.result_ready.connect(self._on_summary_result)
        worker.finished.connect(self._on_summary_finished)
        worker.start()

    def _on_summary_result(self, result: Result) -> None:
        payload = dict((result.data or {})) if getattr(result, "success", False) else {}
        self._apply_cost_items_summary(payload.get("cost_items_result"))
        self._apply_brand_summary(payload.get("brands_result"))
        self._apply_catalog_company_summary(payload.get("companies_result"))

    def _on_summary_finished(self) -> None:
        worker = self._summary_worker
        if worker is not None:
            worker.deleteLater()
        self._summary_worker = None
        if self._summary_refresh_pending:
            self._summary_refresh_pending = False
            QTimer.singleShot(0, self._refresh_summary_async)

    def _apply_cost_items_summary(self, result) -> None:
        if not getattr(result, "success", False):
            return
        records = (getattr(result, "data", None) or {}).get("records") or []
        self._sync_pending_quick_badge("cost_items", len(records))

    def _apply_brand_summary(self, result) -> None:
        if getattr(result, "success", False) and self._is_quick_target_visible("brands"):
            self._clear_quick_badge("brands")

    def _apply_catalog_company_summary(self, result) -> None:
        if getattr(result, "success", False) and self._is_quick_target_visible("companies"):
            self._clear_quick_badge("companies")

    def _apply_quick_access_badges(self) -> None:
        self.cost_items_btn.setBadgeCount(int(self._quick_badges.get("cost_items", 0)))
        self.cost_items_btn.setActive(True)
        self.brands_btn.setBadgeCount(int(self._quick_badges.get("brands", 0)))
        self.brands_btn.setActive(True)
        self.companies_btn.setBadgeCount(int(self._quick_badges.get("companies", 0)))
        self.companies_btn.setActive(True)

    def _clear_quick_badge(self, key: str) -> None:
        if key not in self._quick_badges:
            return
        if key in self._pending_seen_counts:
            self._pending_seen_counts[key] = max(0, int(self._pending_current_counts.get(key, 0)))
        self._quick_badges[key] = 0
        self._apply_quick_access_badges()

    def _increment_quick_badge(self, key: str, delta: int = 1) -> None:
        if key not in self._quick_badges:
            return
        if self._is_quick_target_visible(key):
            self._quick_badges[key] = 0
        else:
            self._quick_badges[key] = max(0, int(self._quick_badges.get(key, 0)) + max(1, int(delta or 1)))
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
        if key == "cost_items":
            return bool(self.cost_items_window is not None and self.cost_items_window.isVisible())
        if key == "brands":
            return bool(self._brand_dialog is not None and self._brand_dialog.isVisible())
        if key == "companies":
            return bool(self._company_dialog is not None and self._company_dialog.isVisible())
        return False

    def _on_cost_items_changed(self) -> None:
        self._refresh_cost_items_summary()

    def _normalize_stock_quick_key(self, section: str) -> str:
        raw = str(section or "").strip().lower()
        if raw in {"brand", "brands"}:
            return "brands"
        if raw in {"company", "companies"}:
            return "companies"
        return ""

    def _on_stock_quick_access_changed(self, section: str, delta: int) -> None:
        norm = self._normalize_stock_quick_key(section)
        if not norm:
            return
        self._increment_quick_badge(norm, delta)


    def open_cost_items_window(self) -> None:
        try:
            from .finance_cost_items_window import FinanceCostItemsWindow

            created = self.cost_items_window is None
            if self.cost_items_window is None:
                self.cost_items_window = FinanceCostItemsWindow()
                self.cost_items_window.itemsChanged.connect(self._on_cost_items_changed)
            self._clear_quick_badge("cost_items")
            self.cost_items_window.showMaximized()
            self.cost_items_window.raise_()
            self.cost_items_window.activateWindow()
            if not created:
                reload_fn = getattr(self.cost_items_window, "request_reload_items", None)
                if not callable(reload_fn):
                    reload_fn = getattr(self.cost_items_window, "reload_items", None)
                if callable(reload_fn):
                    reload_fn()
        except Exception as exc:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(exc), error=exc, close_dialog=False),
                only_errors=True,
            )

    def open_invoices_window(self) -> None:
        try:
            from .finance_manager_window import FinanceManagerWindow

            created = self.invoices_window is None
            if self.invoices_window is None:
                self.invoices_window = FinanceManagerWindow()
            self.invoices_btn.setActive(True)
            self.invoices_window.showMaximized()
            self.invoices_window.raise_()
            self.invoices_window.activateWindow()
            if not created:
                self.invoices_window.reload_from_db()
        except Exception as exc:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(exc), error=exc, close_dialog=False),
                only_errors=True,
            )

    def open_transactions_window(self) -> None:
        try:
            from .finance_transactions_window import FinanceTransactionsWindow

            created = self.transactions_window is None
            if self.transactions_window is None:
                self.transactions_window = FinanceTransactionsWindow()
            self.transactions_btn.setActive(True)
            self.transactions_window.showMaximized()
            self.transactions_window.raise_()
            self.transactions_window.activateWindow()
            if not created:
                self.transactions_window.reload_from_db()
        except Exception as exc:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(exc), error=exc, close_dialog=False),
                only_errors=True,
            )

    def open_brand_manager_window(self) -> None:
        try:
            from .finance_brand_manager_window import FinanceBrandManagerDialog

            if self._brand_dialog is None:
                dialog = FinanceBrandManagerDialog(self)
                dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
                dialog.destroyed.connect(self._on_brand_dialog_closed)
                self._brand_dialog = dialog
            self._clear_quick_badge("brands")
            self._brand_dialog.open_full()
        except Exception as exc:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(exc), error=exc, close_dialog=False),
                only_errors=True,
            )

    def _on_brand_dialog_closed(self, *_args) -> None:
        self._brand_dialog = None
        self._refresh_brand_summary()
        self._clear_quick_badge("brands")

    def open_company_manager_window(self) -> None:
        try:
            from .finance_company_manager_window import FinanceCompanyManagerDialog

            if self._company_dialog is None:
                dialog = FinanceCompanyManagerDialog(self)
                dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
                dialog.destroyed.connect(self._on_company_dialog_closed)
                self._company_dialog = dialog
            self._clear_quick_badge("companies")
            self._company_dialog.open_full()
        except Exception as exc:
            MessageHandler.show(
                self,
                Result.fail(map_error_to_message(exc), error=exc, close_dialog=False),
                only_errors=True,
            )

    def _on_company_dialog_closed(self, *_args) -> None:
        self._company_dialog = None
        self._refresh_catalog_company_summary()
        self._clear_quick_badge("companies")


_window_exports = {
    "FinanceCargoTariffCard": ("Logistics.views.cargo_tariffs_window", "FinanceCargoTariffCard"),
    "FinanceCargoTariffsWindow": ("Logistics.views.cargo_tariffs_window", "FinanceCargoTariffsWindow"),
    "FinanceBrandManagerDialog": (".finance_brand_manager_window", "FinanceBrandManagerDialog"),
    "FinanceCompanyManagerDialog": (".finance_company_manager_window", "FinanceCompanyManagerDialog"),
    "FinanceCostItemCard": (".finance_cost_items_window", "FinanceCostItemCard"),
    "FinanceCostItemsWindow": (".finance_cost_items_window", "FinanceCostItemsWindow"),
    "FinanceInvoiceCard": (".finance_manager_window", "FinanceInvoiceCard"),
    "FinanceManagerWindow": (".finance_manager_window", "FinanceManagerWindow"),
    "FinanceTransactionWorkspaceRecord": (".finance_transactions_window", "FinanceTransactionWorkspaceRecord"),
    "FinanceTransactionsWindow": (".finance_transactions_window", "FinanceTransactionsWindow"),
}


def __getattr__(name: str):
    target = _window_exports.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module_name, attr_name = target
    value = getattr(import_module(module_name, __package__ if module_name.startswith(".") else None), attr_name)
    globals()[name] = value
    return value


__all__ = [
    "FINANCE_STYLE",
    "FinanceCargoTariffCard",
    "FinanceCargoTariffsWindow",
    "FinanceBrandManagerDialog",
    "FinanceCompanyManagerDialog",
    "FinanceCostItemCard",
    "FinanceCostItemsWindow",
    "FinanceInvoiceCard",
    "FinanceManagerWindow",
    "FinanceTransactionWorkspaceRecord",
    "FinanceTransactionsWindow",
    "FinanceTab",
    "OrdersStyleCardRecord",
    "OrdersStyleListWidget",
]
