from __future__ import annotations

import os
import unittest
from types import MethodType
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QThread
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QTabWidget, QTextBrowser, QWidget

import Main_interface.views as main_interface_views
import main as desktop_main
from Main_interface.views import views as main_interface_views_impl
from Main_interface.views.lazy_tab_host import LazyTabHost


class TestMainInterfaceViews(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in list(self._app.topLevelWidgets()):
            try:
                widget.close()
            except Exception:
                pass
            try:
                widget.deleteLater()
            except Exception:
                pass
        self._app.processEvents()

    def _add_window_cleanup(self, window: QWidget) -> None:
        self.addCleanup(self._app.processEvents)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)

    def test_main_window_uses_explicit_minimum_size(self) -> None:
        with patch.object(main_interface_views, "ENABLE_TEST_LAB_UI", False):
            window = main_interface_views.MainInterface()

        self._add_window_cleanup(window)
        self.assertEqual(window.minimumWidth(), 1000)
        self.assertEqual(window.minimumHeight(), 700)

    def test_release_shell_hides_ai_without_loading_or_removing_ai_code(self) -> None:
        with patch.object(main_interface_views, "ENABLE_TEST_LAB_UI", False), \
             patch.object(main_interface_views_impl, "DEFAULT_ENABLE_AI_UI", False):
            window = main_interface_views.MainInterface()

        self._add_window_cleanup(window)
        ai_index = window._index_for_tab_key("ai")

        self.assertFalse(window._show_ai_ui)
        self.assertIsNone(window.ai_toolbar_action)
        self.assertGreaterEqual(ai_index, 0)
        self.assertFalse(window.tabs.isTabVisible(ai_index))
        self.assertFalse(window._tab_hosts["ai"].is_loaded())

    def test_lazy_tabs_only_load_final_tab_after_rapid_switch(self) -> None:
        build_counts: dict[str, int] = {}

        def build_widget(name: str) -> QWidget:
            build_counts[name] = build_counts.get(name, 0) + 1
            widget = QWidget()
            QLabel(name, widget)
            return widget

        with patch.object(main_interface_views, "ENABLE_TEST_LAB_UI", False), \
             patch.object(main_interface_views.MainInterface, "_build_orders_tab", staticmethod(lambda: build_widget("orders"))), \
             patch.object(main_interface_views.MainInterface, "_build_stock_tab", staticmethod(lambda: build_widget("stock"))), \
             patch.object(main_interface_views.MainInterface, "_build_listing_tab", staticmethod(lambda: build_widget("listing"))), \
             patch.object(main_interface_views.MainInterface, "_build_marketplaces_tab", staticmethod(lambda: build_widget("marketplaces"))), \
             patch.object(main_interface_views.MainInterface, "_build_finance_tab", staticmethod(lambda: build_widget("finance"))), \
             patch.object(main_interface_views.MainInterface, "_build_logistics_tab", staticmethod(lambda: build_widget("logistics"))):
            window = main_interface_views.MainInterface()

        self._add_window_cleanup(window)

        window.show()
        self._app.processEvents()
        QTest.qWait(main_interface_views._TAB_LOAD_DEBOUNCE_MS + 20)
        self._app.processEvents()

        self.assertEqual(build_counts.get("orders"), 1)
        self.assertNotIn("stock", build_counts)

        window.tabs.setCurrentIndex(1)
        self._app.processEvents()
        window.tabs.setCurrentIndex(2)
        self._app.processEvents()
        window.tabs.setCurrentIndex(3)
        self._app.processEvents()

        self.assertEqual(build_counts.get("orders"), 1)
        self.assertNotIn("stock", build_counts)
        self.assertNotIn("listing", build_counts)
        self.assertNotIn("marketplaces", build_counts)

        QTest.qWait(main_interface_views._TAB_LOAD_DEBOUNCE_MS + 40)
        self._app.processEvents()

        self.assertEqual(build_counts.get("marketplaces"), 1)
        self.assertNotIn("stock", build_counts)
        self.assertNotIn("listing", build_counts)

    def test_ai_toolbar_action_opens_ai_chat_tab(self) -> None:
        build_counts: dict[str, int] = {}

        def build_widget(name: str) -> QWidget:
            build_counts[name] = build_counts.get(name, 0) + 1
            widget = QWidget()
            QLabel(name, widget)
            return widget

        tabs = QTabWidget()
        self._add_window_cleanup(tabs)
        orders_host = LazyTabHost(factory=lambda: build_widget("orders"), loading_text="Orders")
        ai_host = LazyTabHost(factory=lambda: build_widget("ai"), loading_text="AI")
        tabs.addTab(orders_host, "Orders")
        tabs.addTab(ai_host, "AI")
        self._app.processEvents()

        window = SimpleNamespace(
            _show_ai_ui=True,
            _tab_hosts={"orders": orders_host, "ai": ai_host},
            tabs=tabs,
            _deferred_work_started=True,
        )

        def load_current_tab_now() -> None:
            current = tabs.currentWidget()
            if isinstance(current, LazyTabHost):
                current.request_load()

        window._load_current_tab_now = load_current_tab_now
        window._index_for_tab_key = MethodType(main_interface_views.MainInterface._index_for_tab_key, window)
        window._activate_ai_tab = MethodType(main_interface_views.MainInterface._activate_ai_tab, window)

        self.assertIs(tabs.currentWidget(), orders_host)
        self.assertNotIn("ai", build_counts)

        window._activate_ai_tab()
        self._app.processEvents()
        QTest.qWait(main_interface_views._TAB_LOAD_DEBOUNCE_MS + 20)
        self._app.processEvents()

        self.assertIs(tabs.currentWidget(), ai_host)
        self.assertEqual(build_counts.get("ai"), 1)

    def test_main_source_ai_builder_returns_current_clickable_chat_tab(self) -> None:
        from AI.views.chat_tab import AITab

        tab = main_interface_views.MainInterface._build_ai_tab()
        self._add_window_cleanup(tab)

        self.assertIsInstance(tab, AITab)
        self.assertIsInstance(tab.transcript, QTextBrowser)
        self.assertFalse(tab.transcript.openLinks())
        self.assertFalse(tab.transcript.openExternalLinks())

    def test_main_source_acceptance_surface_uses_full_shell_and_lazy_ai_path(self) -> None:
        from AI.views.chat_tab import AITab

        window, tab = desktop_main.build_source_app_ai_acceptance_surface(self._app)
        self._add_window_cleanup(window)

        self.assertIsInstance(window, main_interface_views.MainInterface)
        self.assertIsInstance(tab, AITab)
        self.assertIs(window.tabs.currentWidget(), window._tab_hosts["ai"])
        self.assertIs(window._tab_hosts["ai"].content, tab)

    def test_idle_preload_warms_imports_without_building_hidden_tabs(self) -> None:
        warmed: list[tuple[str, tuple[str, ...]]] = []

        orders_host = LazyTabHost(factory=QWidget, loading_text="Orders")
        logistics_host = LazyTabHost(factory=QWidget, loading_text="Logistics")
        self.addCleanup(self._app.processEvents)
        self.addCleanup(logistics_host.deleteLater)
        self.addCleanup(orders_host.deleteLater)

        class _FakeTabs:
            def currentWidget(self):
                return orders_host

            def indexOf(self, host):
                return {orders_host: 0, logistics_host: 1}.get(host, -1)

            def isTabVisible(self, _index):
                return True

            def tabBar(self):
                return None

        def fake_warmup(key: str, module_names: tuple[str, ...]) -> None:
            warmed.append((key, module_names))
            fake_window._tab_import_warmup_done.add(key)

        fake_window = SimpleNamespace(
            _tab_import_warmup_worker=None,
            _tab_hosts={"orders": orders_host, "logistics": logistics_host},
            _tab_import_warmup_done=set(),
            _tab_import_modules={
                "orders": ("Orders.views.views",),
                "logistics": ("Logistics.views.views", "Logistics.views.actions", "Finance.views.actions"),
            },
            tabs=_FakeTabs(),
            _start_tab_import_warmup=fake_warmup,
        )

        main_interface_views.MainInterface._preload_next_idle_tab(fake_window)

        self.assertEqual(
            warmed,
            [("logistics", ("Logistics.views.views", "Logistics.views.actions", "Finance.views.actions"))],
        )
        self.assertFalse(logistics_host.is_loaded())

    def test_lazy_tab_request_load_defers_factory_until_event_loop(self) -> None:
        calls: list[str] = []

        def build_widget() -> QWidget:
            calls.append("built")
            return QWidget()

        host = LazyTabHost(factory=build_widget, loading_text="Loading")
        self._add_window_cleanup(host)

        host.request_load()

        self.assertEqual(calls, [])
        QTest.qWait(1)
        self._app.processEvents()
        self.assertEqual(calls, ["built"])
        self.assertTrue(host.is_loaded())

    def test_idle_import_warmup_runs_on_gui_thread(self) -> None:
        imported: list[tuple[str, bool]] = []

        class _FakeTabs:
            def currentWidget(self):
                return None

        class _FakeTimer:
            def __init__(self) -> None:
                self.started = False

            def start(self, *_args) -> None:
                self.started = True

        class _FakeWindow:
            pass

        window = _FakeWindow()
        window._tab_import_warmup_worker = None
        window._tab_import_warmup_active = False
        window._tab_import_warmup_key = ""
        window._tab_import_warmup_modules = ()
        window._tab_import_warmup_done = set()
        window._tab_hosts = {}
        window._tab_deferred_load_key = ""
        window._deferred_work_started = False
        window._is_closing = False
        window._tab_preload_timer = _FakeTimer()
        window.tabs = _FakeTabs()
        window._key_for_tab_widget = MethodType(main_interface_views.MainInterface._key_for_tab_widget, window)
        window._on_tab_import_warmed = MethodType(main_interface_views.MainInterface._on_tab_import_warmed, window)
        window._on_tab_import_warmup_finished = MethodType(
            main_interface_views.MainInterface._on_tab_import_warmup_finished,
            window,
        )
        window._run_tab_import_warmup_on_gui_thread = MethodType(
            main_interface_views.MainInterface._run_tab_import_warmup_on_gui_thread,
            window,
        )

        def fake_import(module_name: str):
            imported.append((module_name, QThread.currentThread() is self._app.thread()))
            return object()

        with patch.object(main_interface_views_impl, "import_module", side_effect=fake_import):
            main_interface_views.MainInterface._start_tab_import_warmup(
                window,
                "orders",
                ("Orders.views.views",),
            )
            QTest.qWait(1)
            self._app.processEvents()

        self.assertEqual(imported, [("Orders.views.views", True)])
        self.assertIn("orders", window._tab_import_warmup_done)
        self.assertFalse(window._tab_import_warmup_active)
        self.assertFalse(window._tab_preload_timer.started)


if __name__ == "__main__":
    unittest.main()
