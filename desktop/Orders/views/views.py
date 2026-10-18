from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QSignalBlocker, QTimer

from Core.views import CircularProgressButton, BadgeButton, SwitchButton, NumberStepper, ActionPulseButton, ResettableSplitter
from Orders.constants import ui_text
from Core.views.tab_widgets import DashboardHeroCard, QuickAccessSection, SplitPanelSidebar
from Core.threads.sync_worker import SyncWorker

from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message

from Account.signals.signals import account_signals
from Orders.signals.signals import order_signals
from Orders.constants import (
    ORDERS_AUTO_FETCH_ACTIVE_TEMPLATE,
    ORDERS_AUTO_FETCH_LABEL,
    ORDERS_AUTO_FETCH_STOPPED_TEXT,
    ORDERS_AUTO_FETCH_UNIT_TEXT,
    ORDERS_BADGE_BUTTON_TEXT,
    ORDERS_FETCH_BUTTON_TEXT,
    ORDERS_FETCH_PANEL_TITLE,
    ORDERS_QUICK_ACCESS_SUBTITLE,
    ORDERS_QUICK_ACCESS_TITLE,
    ORDERS_RETURNS_BUTTON_TEXT,
    ORDERS_STATUS_FETCHING_TEXT,
    ORDERS_STATUS_IDLE_TEXT,
    ORDERS_STATUS_OPERATION_FAILED_TEXT,
    ORDERS_STATUS_SAVED_BOTH_TEXT,
    ORDERS_STATUS_SAVED_ORDERS_TEXT,
    ORDERS_STATUS_SAVED_RETURNS_TEXT,
    ORDERS_STATUS_UPDATED_TEXT,
    ORDERS_STATUS_UP_TO_DATE_TEXT,
    ORDERS_STATUS_WARNING_NO_CHANGES_TEMPLATE,
    ORDERS_STATUS_WARNING_TEMPLATE,
    ORDERS_STYLE,
    ORDERS_TAB_ACTION_TEXT,
    ORDERS_TAB_HERO_SUBTITLE,
    ORDERS_TAB_HERO_TITLE,
    ORDERS_WORKSPACE_LEFT_COLLAPSE_TRIGGER,
    ORDERS_WORKSPACE_LEFT_STICK_SIZE,
)
from Orders.constants.paths import (
    ORDERS_FETCH_PANEL_ICON_PATH,
    ORDERS_MANAGER_ICON_PATH,
    ORDERS_RETURNS_ICON_PATH,
)

if TYPE_CHECKING:
    from Account.views.company_list_widget import CompanyListWidget
    from Orders.views.orders_manager_window import (
        OrdersListDelegate,
        OrdersListModel,
        OrdersListWidget,
        OrdersManagerWindow,
        OrdersWorkspaceBehaviorAdapter,
    )
    from Orders.views.returns_manager_window import ReturnsManagerWindow

class OrdersTab(QWidget):
    def __init__(self):
        super().__init__()

        self.setObjectName("OrdersRoot")
        self.setStyleSheet(ORDERS_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        hero = DashboardHeroCard(
            title=ORDERS_TAB_HERO_TITLE,
            subtitle=ORDERS_TAB_HERO_SUBTITLE,
            action_text=ORDERS_TAB_ACTION_TEXT,
        )
        if hero.action_button is not None:
            hero.action_button.clicked.connect(self.open_orders_window)
        root.addWidget(hero)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)
        root.addLayout(content_row, 1)

        self._panel_sidebar = SplitPanelSidebar(self, sidebar_width=92)
        self._panel_sidebar.add_panel_button(
            "fetch",
            "",
            tooltip=str(ui_text("orders.sidebar.fetch_tooltip", "Veri çekme paneli")),
            icon_path=str(ORDERS_FETCH_PANEL_ICON_PATH),
            shape="circular",
            icon_scale=1.28,
        )
        self._panel_sidebar.panel_toggled.connect(self._on_panel_sidebar_toggled)
        content_row.addWidget(self._panel_sidebar)

        splitter = ResettableSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(True)
        splitter.setHandleWidth(6)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        splitter.splitterMoved.connect(self._on_tab_splitter_moved)
        content_row.addWidget(splitter, 1)
        self._tab_splitter = splitter
        self._splitter_guard = False
        self._left_stick_size = ORDERS_WORKSPACE_LEFT_STICK_SIZE
        self._left_collapse_trigger = ORDERS_WORKSPACE_LEFT_COLLAPSE_TRIGGER

        left_card = QFrame()
        left_card.setObjectName("SectionCard")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(14, 12, 14, 12)
        left_layout.setSpacing(10)

        left_layout.addWidget(QLabel(ORDERS_FETCH_PANEL_TITLE, objectName="SectionTitle"))

        self.no_company_card = QFrame()
        self.no_company_card.setObjectName("QuickCard")
        no_company_layout = QVBoxLayout(self.no_company_card)
        no_company_layout.setContentsMargins(12, 10, 12, 10)
        no_company_layout.setSpacing(8)
        no_company_title = QLabel(str(ui_text("orders.fetch_panel.no_company_title", "Henüz şirket yok")), objectName="SectionTitle")
        self.no_company_hint = QLabel(
            str(
                ui_text(
                    "orders.fetch_panel.no_company_hint",
                    "Sipariş çekmeden önce en az bir şirket hesabı eklemelisin."
                )
            )
        )
        self.no_company_hint.setObjectName("Muted")
        self.no_company_hint.setWordWrap(True)
        self.btn_add_company = ActionPulseButton(
            text=str(ui_text("orders.fetch_panel.add_company_button", "Şirket Ekle")),
            center_text=True,
        )
        self.btn_add_company.setMinimumWidth(220)
        self.btn_add_company.setEnabled(True)
        self.btn_add_company.clicked.connect(self._open_company_manager_from_fetch_panel)
        no_company_layout.addWidget(no_company_title)
        no_company_layout.addWidget(self.no_company_hint)
        no_company_layout.addWidget(self.btn_add_company, alignment=Qt.AlignmentFlag.AlignLeft)
        left_layout.addWidget(self.no_company_card)

        from Account.views.company_list_widget import CompanyListWidget

        self.company_list = CompanyListWidget()
        self.company_list.setMinimumWidth(260)
        self.company_list.companies_loaded.connect(lambda *_args: self._refresh_company_list_state())
        left_layout.addWidget(self.company_list)

        self.fetch_button = CircularProgressButton(ORDERS_FETCH_BUTTON_TEXT, size_scale=1.2)
        self.fetch_button.clicked.connect(self.get_orders)
        left_layout.addWidget(self.fetch_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        auto_card = QFrame()
        auto_card.setObjectName("QuickCard")
        auto_card.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        auto_card_layout = QHBoxLayout(auto_card)
        auto_card_layout.setContentsMargins(10, 8, 10, 8)
        auto_card_layout.setSpacing(10)

        auto_label = QLabel(ORDERS_AUTO_FETCH_LABEL, objectName="Muted")
        self.auto_fetch_toggle = SwitchButton()
        self.auto_fetch_toggle.setChecked(False)
        self.auto_fetch_toggle.clicked.connect(self._toggle_auto_fetch)

        self.auto_fetch_minutes = NumberStepper(minimum=2, maximum=120, step=1)
        self.auto_fetch_minutes.setValue(2)
        self.auto_fetch_minutes.setEnabled(False)
        self.auto_fetch_minutes.setFixedWidth(90)
        self.auto_fetch_minutes.valueChanged.connect(self._on_auto_fetch_minutes_changed)

        unit_label = QLabel(ORDERS_AUTO_FETCH_UNIT_TEXT, objectName="Muted")
        unit_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        time_inline = QHBoxLayout()
        time_inline.setContentsMargins(0, 0, 0, 0)
        time_inline.setSpacing(6)
        time_inline.addWidget(self.auto_fetch_minutes)
        time_inline.addWidget(unit_label)

        auto_card_layout.addWidget(auto_label)
        auto_card_layout.addLayout(time_inline)
        auto_card_layout.addWidget(self.auto_fetch_toggle)
        auto_card_layout.addStretch(1)
        left_layout.addWidget(auto_card)
        self.auto_fetch_card = auto_card

        self.status_label = QLabel(ORDERS_STATUS_IDLE_TEXT)
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)

        self._auto_fetch_interval = 120
        self.fetch_button.setRepeatInterval(self._auto_fetch_interval)
        account_signals.company_changed.connect(self._on_companies_changed)

        splitter.addWidget(left_card)

        right_card = QuickAccessSection(
            title=ORDERS_QUICK_ACCESS_TITLE,
            subtitle=ORDERS_QUICK_ACCESS_SUBTITLE,
        )
        right_layout = right_card.body_layout

        self.order_btn = BadgeButton(
            ORDERS_BADGE_BUTTON_TEXT,
            icon_path=str(ORDERS_MANAGER_ICON_PATH),
            icon_size=48,
            size_scale=1.6632,
        )
        self.order_btn.setMinimumHeight(100)
        self.order_btn.clicked.connect(self.open_orders_window)

        returns_icon_path = ORDERS_RETURNS_ICON_PATH if ORDERS_RETURNS_ICON_PATH.exists() else ORDERS_MANAGER_ICON_PATH

        self.return_btn = BadgeButton(
            ORDERS_RETURNS_BUTTON_TEXT,
            icon_path=str(returns_icon_path),
            icon_size=48,
            size_scale=1.6632,
        )
        self.return_btn.setMinimumHeight(100)
        self.return_btn.clicked.connect(self.open_returns_window)

        quick_btn_row = QHBoxLayout()
        quick_btn_row.setContentsMargins(0, 0, 0, 0)
        quick_btn_row.setSpacing(12)
        quick_btn_row.addWidget(self.order_btn)
        quick_btn_row.addWidget(self.return_btn)
        quick_btn_row.addStretch(1)

        right_layout.addLayout(quick_btn_row)
        right_layout.addStretch(1)

        splitter.addWidget(right_card)
        splitter.setSizes([520, 1020])

        self._sync_sidebar_state_from_splitter()

        self.orders_window = None
        self.returns_window = None
        self._order_stock_sync_workers: list[SyncWorker] = []
        self._bind_order_stock_sync()

    def _bind_order_stock_sync(self) -> None:
        try:
            order_signals.orders_persisted.disconnect(self._on_orders_persisted_for_stock_sync)
        except Exception:
            pass
        order_signals.orders_persisted.connect(self._on_orders_persisted_for_stock_sync)

    def _on_orders_persisted_for_stock_sync(self, payload: dict) -> None:
        order_items = list((payload or {}).get("order_item_list") or [])
        if not order_items:
            return

        from Stock.views.actions import action_auto_deduct_order_items

        worker = SyncWorker(
            action_auto_deduct_order_items,
            parent=self,
            order_item_list=order_items,
            created_by="orders:auto",
        )
        self._order_stock_sync_workers.append(worker)
        worker.result_ready.connect(self._on_order_stock_sync_result)
        worker.finished.connect(lambda w=worker: self._cleanup_order_stock_sync_worker(w))
        worker.start()

    def _on_order_stock_sync_result(self, result: object) -> None:
        if not isinstance(result, Result):
            return
        data = result.data or {}
        if not result.success or int(data.get("tx_failed", 0) or 0) > 0:
            print(f"[orders->stock] auto deduct failed: {result.message} | {data}")
            return

        tx_created = int(data.get("tx_created", 0) or 0)
        tx_duplicate = int(data.get("tx_duplicate", 0) or 0)
        unmatched = int(data.get("unmatched_lines", 0) or 0)
        if tx_created or tx_duplicate or unmatched:
            print(
                "[orders->stock] auto deduct "
                f"created={tx_created} duplicate={tx_duplicate} unmatched={unmatched}"
            )

    def _cleanup_order_stock_sync_worker(self, worker: SyncWorker) -> None:
        try:
            self._order_stock_sync_workers.remove(worker)
        except ValueError:
            pass

    def _release_splitter_guard(self):
        self._splitter_guard = False
        self._sync_sidebar_state_from_splitter()

    def _is_fetch_panel_open(self) -> bool:
        sizes = self._tab_splitter.sizes()
        if len(sizes) < 2:
            return False
        return int(sizes[0]) > 8

    def _sync_sidebar_state_from_splitter(self):
        if hasattr(self, "_panel_sidebar") and self._panel_sidebar is not None:
            self._panel_sidebar.set_active_panel("fetch" if self._is_fetch_panel_open() else None)

    def _splitter_total_size(self) -> int:
        sizes = self._tab_splitter.sizes()
        total = int(sum(sizes)) if sizes else 0
        if total > 0:
            return total
        width = int(self._tab_splitter.width() or 0)
        if width > 0:
            return width
        return self._left_stick_size + 980

    def _snap_splitter(self, left: int, total: int):
        self._splitter_guard = True
        clamped = max(0, int(left))
        self._tab_splitter.setSizes([clamped, max(0, int(total) - clamped)])
        QTimer.singleShot(0, self._release_splitter_guard)

    def _open_fetch_panel(self):
        if self._is_fetch_panel_open():
            self._sync_sidebar_state_from_splitter()
            return
        total = self._splitter_total_size()
        min_left = 320
        target = max(min_left, min(self._left_stick_size, total - 320))
        if target <= 0:
            target = min_left
        self._snap_splitter(target, total)
        self._sync_sidebar_state_from_splitter()

    def _close_fetch_panel(self):
        if not self._is_fetch_panel_open():
            self._sync_sidebar_state_from_splitter()
            return
        total = self._splitter_total_size()
        self._snap_splitter(0, total)
        self._sync_sidebar_state_from_splitter()

    def _on_panel_sidebar_toggled(self, panel_id: str, active: bool):
        if panel_id != "fetch":
            return
        if active:
            self._open_fetch_panel()
        else:
            self._close_fetch_panel()

    def _on_tab_splitter_moved(self, pos: int, _index: int):
        if self._splitter_guard:
            return
        try:
            sizes = self._tab_splitter.sizes()
            if len(sizes) < 2:
                return
            left, right = int(sizes[0]), int(sizes[1])
            total = left + right
            if total <= 0:
                return
            if left >= self._left_stick_size:
                return
            if pos <= self._left_collapse_trigger:
                self._snap_splitter(0, total)
                return
            if left < self._left_stick_size:
                self._snap_splitter(self._left_stick_size, total)
        except Exception:
            self._splitter_guard = False
        self._sync_sidebar_state_from_splitter()


    def get_orders(self):
        from Orders.views.actions import get_orders_from_companies

        if self.company_list.count() == 0:
            self._refresh_company_list_state(reload_companies=True)
            MessageHandler.show(
                self,
                Result.fail(
                    str(ui_text("orders.fetch_panel.no_company_error", "Kayıtlı şirket bulunamadı. Önce şirket eklemelisin.")),
                    close_dialog=False,
                ),
                only_errors=True,
            )
            return

        if not self.fetch_button.isEnabled():
            return

        self.fetch_button.setEnabled(False)
        self.status_label.setText(ORDERS_STATUS_FETCHING_TEXT)
        if hasattr(self.fetch_button, "setRunningText"):
            self.fetch_button.setRunningText("Hazırlanıyor...")
        self.fetch_button.start()

        res = get_orders_from_companies(self, self.company_list, self.fetch_button)
        if not res.success:
            self.fetch_button.fail()
            self.fetch_button.setEnabled(True)
            MessageHandler.show(self, res, only_errors=True)
            self.status_label.setText(f"⚠️ Orders verileri alınırken hata oluştu: {res.message}")

    def open_orders_window(self):
        try:
            from Orders.views.orders_manager_window import OrdersManagerWindow

            if self.orders_window is None:
                self.orders_window = OrdersManagerWindow()
            self.orders_window.prepare_open_filters()
            self._show_manager_window(self.orders_window)
            # Always refresh on open to catch new DB rows that arrived while window was hidden.
            self._schedule_loaded_manager_reload(self.orders_window)
            self._clear_orders_badge()
        except Exception as e:
            res = Result.fail(map_error_to_message(e), error=e, close_dialog=False)
            MessageHandler.show(self, res, only_errors=True)

    def open_returns_window(self):
        try:
            from Orders.views.returns_manager_window import ReturnsManagerWindow

            if self.returns_window is None:
                self.returns_window = ReturnsManagerWindow()
            self.returns_window.prepare_open_filters()
            self._show_manager_window(self.returns_window)
            self._schedule_loaded_manager_reload(self.returns_window)
            self._clear_returns_badge()
        except Exception as e:
            res = Result.fail(map_error_to_message(e), error=e, close_dialog=False)
            MessageHandler.show(self, res, only_errors=True)

    @staticmethod
    def _schedule_loaded_manager_reload(window: QWidget | None) -> None:
        list_widget = getattr(window, "list_widget", None)
        if list_widget is None:
            return
        worker = getattr(list_widget, "reload_worker", None)
        if worker is not None and worker.isRunning():
            return
        if not getattr(list_widget, "orders", None):
            return
        QTimer.singleShot(0, list_widget.reload_orders)

    @staticmethod
    def _show_manager_window(window: QWidget | None) -> None:
        if window is None:
            return
        try:
            state = window.windowState()
            window.setWindowState((state & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowMaximized)
        except Exception:
            pass
        window.showMaximized()
        try:
            window.raise_()
            window.activateWindow()
        except Exception:
            pass

    def on_orders_failed(self, result: Result, button: CircularProgressButton):
        button.fail()
        button.setEnabled(True)
        MessageHandler.show(self, result, only_errors=True)

        self.status_label.setText(ORDERS_STATUS_OPERATION_FAILED_TEXT)

    def on_orders_fetched(self, result: Result):
        # butona dokunma yok; pipeline finalize zaten ayor
        data = result.data or {}
        changed = bool(data.get("changed"))
        counts = data.get("counts") or {}
        warnings = list(data.get("warnings") or [])
        headers_inserted = int(counts.get("headers_inserted") or 0)
        data_inserted = int(counts.get("data_inserted") or 0)
        items_inserted = int(counts.get("items_inserted") or 0)
        claims_inserted = int(counts.get("claims_inserted") or 0)
        orders_changed = any((headers_inserted, data_inserted, items_inserted))
        if changed:
            if orders_changed and claims_inserted > 0:
                status_text = ORDERS_STATUS_SAVED_BOTH_TEXT
            elif orders_changed:
                status_text = ORDERS_STATUS_SAVED_ORDERS_TEXT
            elif claims_inserted > 0:
                status_text = ORDERS_STATUS_SAVED_RETURNS_TEXT
            else:
                status_text = ORDERS_STATUS_UPDATED_TEXT
            if warnings:
                status_text = ORDERS_STATUS_WARNING_TEMPLATE.format(status_text=status_text, warning=warnings[0])
            self.status_label.setText(status_text)
            badge_count = headers_inserted or data_inserted or items_inserted
            if badge_count > 0:
                self._set_orders_badge(badge_count)
            if claims_inserted > 0:
                self._set_returns_badge(claims_inserted)
        else:
            if warnings:
                self.status_label.setText(ORDERS_STATUS_WARNING_NO_CHANGES_TEMPLATE.format(warning=warnings[0]))
            else:
                self.status_label.setText(ORDERS_STATUS_UP_TO_DATE_TEXT)

    def _set_orders_badge(self, count: int):
        try:
            self.order_btn.setBadgeCount(int(count))
            self.order_btn.setActive(True)
        except Exception:
            pass

    def _clear_orders_badge(self):
        try:
            self.order_btn.setBadgeCount(0)
            self.order_btn.setActive(True)
        except Exception:
            pass

    def _set_returns_badge(self, count: int):
        try:
            self.return_btn.setBadgeCount(int(count))
            self.return_btn.setActive(True)
        except Exception:
            pass

    def _clear_returns_badge(self):
        try:
            self.return_btn.setBadgeCount(0)
            self.return_btn.setActive(True)
        except Exception:
            pass

    def _toggle_auto_fetch(self):
        try:
            if self.auto_fetch_toggle.isChecked():
                self.auto_fetch_minutes.setEnabled(True)
                self._on_auto_fetch_minutes_changed(self.auto_fetch_minutes.value())
                self.fetch_button.enableRepeat(True)
                mins = self.auto_fetch_minutes.value()
                self.status_label.setText(ORDERS_AUTO_FETCH_ACTIVE_TEMPLATE.format(mins=mins))
            else:
                self.auto_fetch_minutes.setEnabled(False)
                self.fetch_button.stopRepeat()
                self.status_label.setText(ORDERS_AUTO_FETCH_STOPPED_TEXT)
        except Exception:
            pass

    def _on_auto_fetch_minutes_changed(self, value: int):
        try:
            mins = max(2, int(value))
            self._auto_fetch_interval = mins * 60
            self.fetch_button.setRepeatInterval(self._auto_fetch_interval)
            if self.auto_fetch_toggle.isChecked():
                self.status_label.setText(ORDERS_AUTO_FETCH_ACTIVE_TEMPLATE.format(mins=mins))
        except Exception:
            pass

    def _on_companies_changed(self):
        QTimer.singleShot(0, self._refresh_company_list_state)

    def _open_company_manager_from_fetch_panel(self):
        try:
            main_window = self.window()
            opener = getattr(main_window, "company_ui", None)
            if opener is not None and hasattr(opener, "open_comp_manage_dialog"):
                opener.open_comp_manage_dialog()
            else:
                from Account.views.views import CompanyManagerDialog
                dialog = CompanyManagerDialog()
                dialog.exec()
        except Exception as e:
            MessageHandler.show(self, Result.fail(map_error_to_message(e), error=e), only_errors=True)
        finally:
            self._refresh_company_list_state(reload_companies=True)

    def _refresh_company_list_state(self, *, reload_companies: bool = False):
        try:
            if reload_companies:
                self.company_list.reload_companies()
                return

            has_companies = self.company_list.count() > 0
            self.no_company_card.setVisible(not has_companies)
            self.company_list.setVisible(has_companies)
            self.fetch_button.setVisible(has_companies)
            self.auto_fetch_card.setVisible(has_companies)
            self.fetch_button.setEnabled(has_companies)

            if not has_companies:
                if self.auto_fetch_toggle.isChecked():
                    with QSignalBlocker(self.auto_fetch_toggle):
                        self.auto_fetch_toggle.setChecked(False)
                self.auto_fetch_minutes.setEnabled(False)
                self.fetch_button.stopRepeat()
                self.status_label.setText(
                    str(
                        ui_text(
                            "orders.fetch_panel.no_company_status",
                            "Henüz ekli şirket yok. Şirket ekleyerek sipariş çekmeye başlayabilirsin."
                        )
                    )
                )
                return

            if self.auto_fetch_toggle.isChecked():
                self.auto_fetch_minutes.setEnabled(True)
            else:
                self.auto_fetch_minutes.setEnabled(False)

            empty_status = str(
                ui_text(
                    "orders.fetch_panel.no_company_status",
                    "Henüz ekli şirket yok. Şirket ekleyerek sipariş çekmeye başlayabilirsin."
                )
            )
            if self.status_label.text().strip() == empty_status:
                self.status_label.setText(str(ui_text("orders.fetch_panel.idle_status", ORDERS_STATUS_IDLE_TEXT)))
        except Exception:
            pass


_WINDOW_EXPORTS = {
    "OrdersListDelegate": (".orders_manager_window", "OrdersListDelegate"),
    "OrdersListModel": (".orders_manager_window", "OrdersListModel"),
    "OrdersListWidget": (".orders_manager_window", "OrdersListWidget"),
    "OrdersManagerWindow": (".orders_manager_window", "OrdersManagerWindow"),
    "OrdersWorkspaceBehaviorAdapter": (".orders_manager_window", "OrdersWorkspaceBehaviorAdapter"),
    "ReturnsManagerWindow": (".returns_manager_window", "ReturnsManagerWindow"),
}


def __getattr__(name: str):
    target = _WINDOW_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module_name, attr_name = target
    value = getattr(import_module(module_name, __package__), attr_name)
    globals()[name] = value
    return value


__all__ = [
    "ORDERS_STYLE",
    "OrdersListDelegate",
    "OrdersListModel",
    "OrdersListWidget",
    "OrdersManagerWindow",
    "OrdersWorkspaceBehaviorAdapter",
    "ReturnsManagerWindow",
    "OrdersTab",
]
