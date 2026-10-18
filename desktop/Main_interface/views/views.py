from __future__ import annotations

import os
import sys
from importlib import import_module
from typing import Callable

from PyQt6.QtCore import QSize, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMainWindow, QToolBar, QWidget

from settings import (
    ASSETS_DIR,
    ENABLE_AI_UI as DEFAULT_ENABLE_AI_UI,
    ENABLE_TEST_LAB_UI as DEFAULT_ENABLE_TEST_LAB_UI,
)
from Main_interface.constants import ui_text
from Main_interface.constants import (
    MAIN_AI_TAB_ICON_SIZE,
    MAIN_TAB_LOADING_TEMPLATE,
    MAIN_TAB_LABELS,
    MAIN_TOOLBAR_ICON_SIZE,
    MAIN_TOOLBAR_STYLE,
    MAIN_TOOLBAR_TITLE,
    MAIN_WINDOW_GEOMETRY,
    MAIN_WINDOW_TITLE,
)
from Core.views.tab_widgets import GlowTabWidget
from .lazy_tab_host import LazyTabHost

_TAB_LOAD_DEBOUNCE_MS = 140
_TAB_PRELOAD_INITIAL_DELAY_MS = 1600
_TAB_PRELOAD_IDLE_DELAY_MS = 1200
_TAB_PRELOAD_STEP_DELAY_MS = 260
_TAB_PRELOAD_PRIORITY = ("logistics", "finance", "listing", "stock", "marketplaces", "orders", "ai")
_MAIN_ICON_CACHE: dict[tuple[str, int, int], QIcon] = {}
_UPDATE_CONTROLLER_CLASS = None


def _main_icon(path: str | os.PathLike[str]) -> QIcon:
    path_text = os.fspath(path)
    try:
        stat = os.stat(path_text)
        signature = (os.path.abspath(path_text), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return QIcon(path_text)
    cached = _MAIN_ICON_CACHE.get(signature)
    if cached is not None:
        return cached
    icon = QIcon(signature[0])
    _MAIN_ICON_CACHE[signature] = icon
    return icon


def _test_lab_enabled() -> bool:
    package_module = sys.modules.get("Main_interface.views")
    if package_module is not None and hasattr(package_module, "ENABLE_TEST_LAB_UI"):
        return bool(getattr(package_module, "ENABLE_TEST_LAB_UI"))
    return bool(DEFAULT_ENABLE_TEST_LAB_UI)


def _update_controller_class():
    global _UPDATE_CONTROLLER_CLASS
    if _UPDATE_CONTROLLER_CLASS is None:
        from Update.views.actions import UpdateController

        _UPDATE_CONTROLLER_CLASS = UpdateController
    return _UPDATE_CONTROLLER_CLASS


class _TabModuleWarmupWorker(QThread):
    warmed = pyqtSignal(str, bool, str)

    def __init__(self, *, key: str, module_names: tuple[str, ...], parent=None) -> None:
        super().__init__(parent)
        self.key = str(key or "").strip()
        self.module_names = tuple(str(name or "").strip() for name in tuple(module_names or ()) if str(name or "").strip())

    def run(self) -> None:
        try:
            for module_name in self.module_names:
                import_module(module_name)
            self.warmed.emit(self.key, True, "")
        except Exception as exc:
            self.warmed.emit(self.key, False, str(exc))


class MainInterface(QMainWindow):
    def __init__(self, *, defer_startup: bool = False, show_ai_ui: bool | None = None):
        super().__init__()
        self._show_ai_ui = DEFAULT_ENABLE_AI_UI if show_ai_ui is None else bool(show_ai_ui)
        self._is_closing = False
        self._defer_startup = bool(defer_startup)
        self._deferred_work_started = False
        self._tab_hosts: dict[str, LazyTabHost] = {}
        self._tab_import_modules: dict[str, tuple[str, ...]] = {}
        self._tab_import_warmup_done: set[str] = set()
        self._tab_import_warmup_worker: _TabModuleWarmupWorker | None = None
        self._tab_import_warmup_active = False
        self._tab_import_warmup_key = ""
        self._tab_import_warmup_modules: tuple[str, ...] = ()
        self._tab_deferred_load_key = ""
        self._tab_load_timer = QTimer(self)
        self._tab_load_timer.setSingleShot(True)
        self._tab_load_timer.setInterval(_TAB_LOAD_DEBOUNCE_MS)
        self._tab_load_timer.timeout.connect(self._load_current_tab_now)
        self._tab_preload_timer = QTimer(self)
        self._tab_preload_timer.setSingleShot(True)
        self._tab_preload_timer.timeout.connect(self._preload_next_idle_tab)
        self.setWindowTitle(str(ui_text("main_interface.window_title", MAIN_WINDOW_TITLE)))
        self.resize(MAIN_WINDOW_GEOMETRY[2], MAIN_WINDOW_GEOMETRY[3])
        self.setMinimumSize(MAIN_WINDOW_GEOMETRY[2], MAIN_WINDOW_GEOMETRY[3])

        main_icon = os.path.join(ASSETS_DIR, "orderscout-logo.png")
        self.setWindowIcon(_main_icon(main_icon))

        self.tabs = GlowTabWidget()
        self.setCentralWidget(self.tabs)

        self.update_controller = None
        self._post_update_timer = QTimer(self)
        self._post_update_timer.setSingleShot(True)
        self._post_update_timer.timeout.connect(self._process_post_update_startup)
        self._startup_check_timer = QTimer(self)
        self._startup_check_timer.setSingleShot(True)
        self._startup_check_timer.timeout.connect(self._schedule_startup_update_check)

        self.init_toolbar()
        self.init_tabs()
        if self._defer_startup:
            self.set_bootstrap_pending(True)
        else:
            self.start_deferred_work()

    def _ensure_update_controller(self):
        controller = self.update_controller
        if controller is None:
            controller_class = _update_controller_class()
            controller = controller_class(self)
            self.update_controller = controller
        return controller

    def _check_updates_from_toolbar(self) -> None:
        self._ensure_update_controller().check_updates_from_toolbar()

    def _process_post_update_startup(self) -> None:
        self._ensure_update_controller().process_post_update_startup()

    def _schedule_startup_update_check(self) -> None:
        self._ensure_update_controller().schedule_startup_check()

    def set_bootstrap_pending(self, pending: bool) -> None:
        enabled = not bool(pending)
        self.tabs.setEnabled(enabled)
        if hasattr(self, "toolBar"):
            self.toolBar.setEnabled(enabled)

    def start_deferred_work(self) -> None:
        if self._deferred_work_started:
            return
        self._deferred_work_started = True
        self.set_bootstrap_pending(False)
        self._tab_load_timer.start()
        self._tab_preload_timer.start(_TAB_PRELOAD_INITIAL_DELAY_MS)
        self._post_update_timer.start(1500)
        self._startup_check_timer.start(2200)

    def init_toolbar(self):
        self.toolBar = QToolBar(MAIN_TOOLBAR_TITLE)
        self.addToolBar(self.toolBar)

        from Account.views.views import CompanyManagerButton
        from Support.views.views import SupportButton
        from Update.views.views import UpdateToolbarButton

        self.company_ui = CompanyManagerButton(self)
        self.toolBar.addAction(self.company_ui.create_action())

        self.support_ui = SupportButton(self)
        self.toolBar.addAction(self.support_ui.create_action())

        self.update_ui = UpdateToolbarButton(
            self,
            trigger_callback=self._check_updates_from_toolbar,
        )
        self.toolBar.addAction(self.update_ui.create_action())

        self.ai_ui = None
        self.ai_toolbar_action = None
        if self._show_ai_ui:
            self.ai_toolbar_action = QAction(_main_icon(ASSETS_DIR / "ai-icon-search.png"), "AI", self)
            self.ai_toolbar_action.setToolTip("OrderScout AI sohbet sekmesini aç")
            self.ai_toolbar_action.setIconText("AI")
            self.ai_toolbar_action.setIconVisibleInMenu(True)
            self.ai_toolbar_action.setData("ai_chat")
            self.ai_toolbar_action.triggered.connect(self._activate_ai_tab)
            self.toolBar.addAction(self.ai_toolbar_action)
            self.ai_toolbar_action.setVisible(True)

        if _test_lab_enabled():
            from Testing.views.views import TestLabButton

            self.test_lab_ui = TestLabButton(self)
            self.toolBar.addAction(self.test_lab_ui.create_action())

        self._apply_toolbar_scale()

    def _apply_toolbar_scale(self) -> None:
        self.toolBar.setIconSize(QSize(*MAIN_TOOLBAR_ICON_SIZE))
        self.toolBar.setStyleSheet(MAIN_TOOLBAR_STYLE)

    @staticmethod
    def _build_orders_tab() -> QWidget:
        from Orders.views.views import OrdersTab

        return OrdersTab()

    @staticmethod
    def _build_stock_tab() -> QWidget:
        from Stock.views.tab import StockTab

        return StockTab()

    @staticmethod
    def _build_listing_tab() -> QWidget:
        from Listing.views.views import ListingTab

        return ListingTab()

    @staticmethod
    def _build_marketplaces_tab() -> QWidget:
        from Marketplaces.views.views import MarketplacesTab

        return MarketplacesTab()

    @staticmethod
    def _build_finance_tab() -> QWidget:
        from Finance.views.views import FinanceTab

        return FinanceTab()

    @staticmethod
    def _build_logistics_tab() -> QWidget:
        from Logistics.views.views import LogisticsTab

        return LogisticsTab()

    @staticmethod
    def _build_ai_tab() -> QWidget:
        from AI.views.chat_tab import AITab

        return AITab()

    def _add_lazy_tab(
        self,
        *,
        key: str,
        label: str,
        icon_name: str,
        factory: Callable[[], QWidget],
        import_module_name: str | tuple[str, ...] = "",
        visible: bool = True,
        animated_gif_name: str | None = None,
        fallback_icon_name: str | None = None,
        animated_size: tuple[int, int] | None = None,
    ) -> LazyTabHost:
        host = LazyTabHost(
            factory=factory,
            loading_text=MAIN_TAB_LOADING_TEMPLATE.format(label=label),
            parent=self.tabs,
        )
        icon = _main_icon(ASSETS_DIR / icon_name)
        index = self.tabs.addTab(host, icon, label)
        self._tab_hosts[key] = host
        if isinstance(import_module_name, tuple):
            module_names = tuple(str(name or "").strip() for name in import_module_name if str(name or "").strip())
        else:
            module_names = (str(import_module_name or "").strip(),) if str(import_module_name or "").strip() else ()
        if module_names:
            self._tab_import_modules[key] = module_names
        setattr(self, f"{key}_tab", host)

        if animated_gif_name:
            fallback_icon = _main_icon(ASSETS_DIR / (fallback_icon_name or icon_name))
            size = QSize(*(animated_size or MAIN_AI_TAB_ICON_SIZE))
            self.tabs.set_animated_tab_icon(
                index,
                str(ASSETS_DIR / animated_gif_name),
                fallback_icon=fallback_icon,
                size=size,
            )

        if not visible:
            try:
                self.tabs.setTabVisible(index, False)
            except Exception:
                bar = self.tabs.tabBar()
                if bar is not None:
                    try:
                        bar.setTabVisible(index, False)
                    except Exception:
                        pass
        return host

    def init_tabs(self):
        self._add_lazy_tab(
            key="orders",
            label=str(ui_text("main_interface.tabs.orders", MAIN_TAB_LABELS["orders"])),
            icon_name="tab-orders-icon.png",
            factory=self._build_orders_tab,
            import_module_name="Orders.views.views",
        )
        self._add_lazy_tab(
            key="stock",
            label=str(ui_text("main_interface.tabs.stock", MAIN_TAB_LABELS["stock"])),
            icon_name="tab-stock-icon.png",
            factory=self._build_stock_tab,
            import_module_name="Stock.views.tab",
        )
        self._add_lazy_tab(
            key="listing",
            label=str(ui_text("main_interface.tabs.listing", MAIN_TAB_LABELS["listing"])),
            icon_name="tab-listing-icon.png",
            factory=self._build_listing_tab,
            import_module_name="Listing.views.views",
        )
        self._add_lazy_tab(
            key="marketplaces",
            label=str(ui_text("main_interface.tabs.marketplaces", MAIN_TAB_LABELS["marketplaces"])),
            icon_name="tab-marketplaces-icon.png",
            factory=self._build_marketplaces_tab,
            import_module_name="Marketplaces.views.views",
        )
        self._add_lazy_tab(
            key="finance",
            label=str(ui_text("main_interface.tabs.finance", MAIN_TAB_LABELS["finance"])),
            icon_name="tab-finance-icon.png",
            factory=self._build_finance_tab,
            import_module_name=("Finance.views.views", "Finance.views.actions"),
        )
        self._add_lazy_tab(
            key="logistics",
            label=str(ui_text("main_interface.tabs.logistics", MAIN_TAB_LABELS["logistics"])),
            icon_name="tab-logistics-icon.png",
            factory=self._build_logistics_tab,
            import_module_name=("Logistics.views.views", "Logistics.views.actions", "Finance.views.actions"),
        )
        self._add_lazy_tab(
            key="ai",
            label=MAIN_TAB_LABELS["ai"],
            icon_name="ai-icon-search.png",
            factory=self._build_ai_tab,
            import_module_name="AI.views.chat_tab",
            visible=self._show_ai_ui,
            animated_gif_name="ai-icon.gif",
            fallback_icon_name="ai-icon-search.png",
            animated_size=MAIN_AI_TAB_ICON_SIZE,
        )

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._set_ai_tab_visible(self._show_ai_ui)

    def _on_tab_changed(self, _index: int) -> None:
        if not self._deferred_work_started:
            return
        if self._tab_preload_timer.isActive():
            self._tab_preload_timer.stop()
        self._tab_load_timer.start()
        self._tab_preload_timer.start(_TAB_PRELOAD_IDLE_DELAY_MS)

    def _key_for_tab_widget(self, widget: QWidget | None) -> str:
        for key, host in self._tab_hosts.items():
            if host is widget:
                return key
        return ""

    def _index_for_tab_key(self, key: str) -> int:
        host = self._tab_hosts.get(str(key or "").strip())
        if host is None:
            return -1
        return self.tabs.indexOf(host)

    def _activate_ai_tab(self) -> None:
        if not self._show_ai_ui:
            return
        index = self._index_for_tab_key("ai")
        if index < 0:
            return
        try:
            self.tabs.setTabVisible(index, True)
        except Exception:
            bar = self.tabs.tabBar()
            if bar is not None and hasattr(bar, "setTabVisible"):
                try:
                    bar.setTabVisible(index, True)
                except Exception:
                    pass
        self.tabs.setCurrentIndex(index)
        if self._deferred_work_started:
            self._load_current_tab_now()

    def _load_current_tab_now(self) -> None:
        if self._tab_load_timer.isActive():
            self._tab_load_timer.stop()
        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, LazyTabHost):
            current_key = self._key_for_tab_widget(current_widget)
            worker = self._tab_import_warmup_worker
            if (
                current_key
                and (
                    (
                        worker is not None
                        and worker.isRunning()
                        and worker.key == current_key
                    )
                    or (
                        self._tab_import_warmup_active
                        and self._tab_import_warmup_key == current_key
                    )
                )
            ):
                self._tab_deferred_load_key = current_key
                return
            current_widget.request_load()

    def _preload_next_idle_tab(self) -> None:
        if self._tab_import_warmup_worker is not None or bool(getattr(self, "_tab_import_warmup_active", False)):
            return
        current_widget = self.tabs.currentWidget()
        warmed_order = list(_TAB_PRELOAD_PRIORITY) + [
            key for key in self._tab_hosts if key not in _TAB_PRELOAD_PRIORITY
        ]
        for key in warmed_order:
            host = self._tab_hosts.get(key)
            if host is current_widget or not isinstance(host, LazyTabHost):
                continue
            if key in self._tab_import_warmup_done or host.is_loaded():
                self._tab_import_warmup_done.add(key)
                continue
            module_names = self._tab_import_modules.get(key, ())
            if not module_names:
                self._tab_import_warmup_done.add(key)
                continue
            index = self.tabs.indexOf(host)
            if index < 0:
                continue
            try:
                if not self.tabs.isTabVisible(index):
                    continue
            except Exception:
                bar = self.tabs.tabBar()
                if bar is not None and hasattr(bar, "isTabVisible") and not bar.isTabVisible(index):
                    continue
            self._start_tab_import_warmup(key, module_names)
            return

    def _start_tab_import_warmup(self, key: str, module_names: tuple[str, ...]) -> None:
        if self._tab_import_warmup_worker is not None or bool(getattr(self, "_tab_import_warmup_active", False)):
            return
        self._tab_import_warmup_active = True
        self._tab_import_warmup_key = str(key or "").strip()
        self._tab_import_warmup_modules = tuple(module_names or ())
        QTimer.singleShot(0, self._run_tab_import_warmup_on_gui_thread)

    def _run_tab_import_warmup_on_gui_thread(self) -> None:
        if self._is_closing:
            return
        key = self._tab_import_warmup_key
        module_names = self._tab_import_warmup_modules
        try:
            for module_name in module_names:
                import_module(module_name)
            self._on_tab_import_warmed(key, True, "")
        except Exception as exc:
            self._on_tab_import_warmed(key, False, str(exc))
        finally:
            self._on_tab_import_warmup_finished()

    def _on_tab_import_warmed(self, key: str, success: bool, message: str) -> None:
        self._tab_import_warmup_done.add(str(key or ""))
        if not success and message:
            print(f"[main tabs] import warmup failed: {key}: {message}")

    def _on_tab_import_warmup_finished(self) -> None:
        worker = self._tab_import_warmup_worker
        if worker is not None:
            worker.deleteLater()
        self._tab_import_warmup_worker = None
        self._tab_import_warmup_active = False
        self._tab_import_warmup_key = ""
        self._tab_import_warmup_modules = ()
        current_key = self._key_for_tab_widget(self.tabs.currentWidget())
        if self._tab_deferred_load_key and self._tab_deferred_load_key == current_key:
            self._tab_deferred_load_key = ""
            QTimer.singleShot(0, self._load_current_tab_now)
            return
        self._tab_deferred_load_key = ""
        if not self._is_closing and self._deferred_work_started:
            self._tab_preload_timer.start(_TAB_PRELOAD_STEP_DELAY_MS)

    def _set_ai_tab_visible(self, visible: bool) -> None:
        index = self.tabs.indexOf(getattr(self, "ai_tab", None))
        if index < 0:
            return
        try:
            self.tabs.setTabVisible(index, bool(visible))
        except Exception:
            bar = self.tabs.tabBar()
            if bar is not None:
                try:
                    bar.setTabVisible(index, bool(visible))
                except Exception:
                    pass

    def closeEvent(self, event) -> None:
        self._is_closing = True
        self._tab_load_timer.stop()
        self._tab_preload_timer.stop()
        worker = self._tab_import_warmup_worker
        if worker is not None and worker.isRunning():
            worker.wait(1500)
        self._tab_import_warmup_active = False
        self._tab_import_warmup_key = ""
        self._tab_import_warmup_modules = ()
        super().closeEvent(event)
