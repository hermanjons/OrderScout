from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QSize, Qt, QTimer, QThread, QSignalBlocker, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from Core.threads.sync_worker import SyncWorker
from Core.views.tab_widgets import GlowTabWidget
from Core.views import (
    NumberStepper,
    AppMessageCenter,
    BadgeButton,
    CircularProgressButton,
    SelectClearToggleButton,
    SwitchSelectWidget,
    optimized_table_updates,
)
from Feedback.processors.pipeline import Result
from settings import ASSETS_DIR, APP_VERSION
from Testing.constants.ui_constants import (
    TEST_LAB_BUILD_MESSAGE_TITLE,
    TEST_LAB_BUILD_OUTPUT_HINT_TEMPLATE,
    TEST_LAB_BUILD_OUTPUT_UNSET_TEXT,
    TEST_LAB_BUILD_STAGE_FAILED_TEXT,
    TEST_LAB_BUILD_STAGE_STARTING_TEXT,
    TEST_LAB_BUILD_SUCCESS_TITLE,
    TEST_LAB_COMPANY_LABEL_TEXT,
    TEST_LAB_DIAGNOSTICS_WINDOW_TITLE,
    TEST_LAB_HEADER_SUBTITLE,
    TEST_LAB_HEADER_TITLE,
    TEST_LAB_LISTING_ORDER_WINDOW_TITLE,
    TEST_LAB_LISTING_SIM_WINDOW_TITLE,
    TEST_LAB_NO_COMPANY_SELECTION_TEXT,
    TEST_LAB_ORDER_WINDOW_TITLE,
    TEST_LAB_REFRESH_COMPANIES_BUTTON_TEXT,
    TEST_LAB_STATUS_BUSY_TEXT,
    TEST_LAB_STATUS_READY_TEXT,
    TEST_LAB_STAGE_WINDOW_TITLE,
    TEST_LAB_TAB_BUILD_TEXT,
    TEST_LAB_TAB_DIAGNOSTICS_TEXT,
    TEST_LAB_TAB_LISTING_TEXT,
    TEST_LAB_TAB_ORDER_TEXT,
    TEST_LAB_TAB_STAGE_TEXT,
    TEST_LAB_WINDOW_MIN_HEIGHT,
    TEST_LAB_WINDOW_MIN_WIDTH,
    TEST_LAB_WINDOW_START_HEIGHT,
    TEST_LAB_WINDOW_START_WIDTH,
    TEST_LAB_WINDOW_TITLE,
)
from Testing.views.actions import (
    action_advance_stage_claim_to_waiting_action,
    action_advance_stage_order_status,
    action_approve_stage_return,
    action_configure_test_chaos,
    action_create_stage_return_claim,
    action_create_stage_test_order,
    action_load_stage_lab_context,
    action_publish_desktop_release,
    action_load_company_listings,
    action_load_test_companies,
    action_run_cargo_tariff_sandbox,
    action_run_domain_healthcheck,
    action_run_label_stress_test,
    action_run_local_unittest_suite,
    action_simulate_listings,
    action_simulate_orders,
    action_simulate_orders_from_listings,
    action_simulate_stock_depletion,
    action_run_stage_return_lifecycle,
    action_verify_listing_order_flow,
)

LIFECYCLE_PRESET_OPTIONS: list[tuple[str, str]] = [
    ("created", "Created"),
    ("shipped", "Shipped"),
    ("delivered", "Delivered"),
    ("cancelled", "Cancelled"),
    ("created_to_shipped", "Created -> Shipped"),
    ("created_to_delivered", "Created -> Delivered"),
    ("created_to_cancelled", "Created -> Cancelled"),
]


def _now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


class _ReleaseBuildWorker(QThread):
    progress_changed = pyqtSignal(int, str)
    log_line = pyqtSignal(str)
    result_ready = pyqtSignal(object)

    def __init__(self, *, version: str, output_root: str, parent=None):
        super().__init__(parent)
        self.version = str(version or "").strip()
        self.output_root = str(output_root or "").strip()

    def run(self) -> None:
        try:
            log_buffer: list[str] = []
            last_emit = time.monotonic()

            def _flush_logs(force: bool = False) -> None:
                nonlocal last_emit
                if not log_buffer:
                    return
                now = time.monotonic()
                if not force and (len(log_buffer) < 20 and (now - last_emit) < 0.2):
                    return
                payload = "\n".join(log_buffer)
                log_buffer.clear()
                last_emit = now
                self.log_line.emit(payload)

            def _on_progress(percent: int, stage: str) -> None:
                self.progress_changed.emit(max(0, min(100, int(percent))), str(stage or ""))

            def _on_log(line: str) -> None:
                text = str(line or "").strip()
                if not text:
                    return
                log_buffer.append(text)
                _flush_logs(force=False)

            res = action_publish_desktop_release(
                version=self.version,
                output_root=self.output_root,
                progress_callback=_on_progress,
                log_callback=_on_log,
            )
            _flush_logs(force=True)
            self.result_ready.emit(res)
        except Exception as e:
            self.result_ready.emit(Result.fail(str(e), error=e, close_dialog=False))


class TestLabDialog(QDialog):
    """
    Centralized in-app test console for simulation and smoke checks.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setSizeGripEnabled(True)
        self.setWindowTitle(TEST_LAB_WINDOW_TITLE)
        self.resize(TEST_LAB_WINDOW_START_WIDTH, TEST_LAB_WINDOW_START_HEIGHT)
        self.setMinimumSize(TEST_LAB_WINDOW_MIN_WIDTH, TEST_LAB_WINDOW_MIN_HEIGHT)

        self._worker: SyncWorker | None = None
        self._build_worker: _ReleaseBuildWorker | None = None
        self._companies: list[dict] = []
        self._last_listing_company_pk: int | None = None
        self._pending_listing_load: bool = False
        self._pending_stage_load: bool = False
        self._listing_row_widgets: list[dict] = []
        self._listing_items_cache: list[dict] = []
        self._listing_total_count: int = 0
        self._last_release_output_dir: str = ""
        self._busy_widgets: list[QWidget] = []

        self.setStyleSheet(
            """
            QDialog {
                background: #F3F6FB;
            }
            QFrame#Card {
                background: #FFFFFF;
                border: 1px solid rgba(15, 23, 42, 0.10);
                border-radius: 12px;
            }
            QFrame#MetricCard {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
            }
            QFrame#ListingOrderRow {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
            }
            QFrame#ListingOrderRow[selected="true"] {
                background: #EFF6FF;
                border: 1px solid #2563EB;
            }
            QScrollArea#ListingCardsScroll {
                background: transparent;
                border: 0px;
            }
            QScrollArea#ListingCardsScroll QWidget {
                background: transparent;
            }
            QScrollArea#DiagnosticsControlsScroll {
                background: transparent;
                border: 0px;
            }
            QLabel#Title {
                font-size: 20px;
                font-weight: 800;
                color: #0F172A;
            }
            QLabel#Muted {
                color: #64748B;
                font-size: 12px;
            }
            QLabel#StatusPill {
                background: rgba(37, 99, 235, 0.12);
                border: 1px solid rgba(37, 99, 235, 0.28);
                border-radius: 12px;
                padding: 4px 10px;
                color: #1D4ED8;
                font-weight: 700;
            }
            QPushButton {
                background: #EEF2FF;
                border: 1px solid #C7D2FE;
                border-radius: 10px;
                padding: 8px 12px;
                font-weight: 700;
                color: #1E3A8A;
            }
            QPushButton:hover {
                background: #E0E7FF;
            }
            QPushButton:pressed {
                background: #C7D2FE;
            }
            QPushButton#PrimaryBtn {
                background: #1D4ED8;
                border: 1px solid #1D4ED8;
                color: #FFFFFF;
            }
            QPushButton#PrimaryBtn:hover {
                background: #1E40AF;
            }
            QComboBox, QLineEdit {
                background: #FFFFFF;
                border: 1px solid rgba(15, 23, 42, 0.20);
                border-radius: 10px;
                padding: 6px 10px;
                min-height: 30px;
            }
            QTextEdit {
                background: #0F172A;
                color: #E2E8F0;
                border: 1px solid #1E293B;
                border-radius: 10px;
                font-family: Consolas;
                font-size: 11px;
            }
            QTableWidget {
                background: #FFFFFF;
                border: 1px solid rgba(15, 23, 42, 0.14);
                border-radius: 10px;
                gridline-color: rgba(15, 23, 42, 0.08);
            }
            QHeaderView::section {
                background: rgba(15, 23, 42, 0.06);
                border: 0px;
                padding: 6px 8px;
                font-weight: 700;
            }
            QSplitter::handle {
                background: rgba(59, 130, 246, 0.15);
                border-radius: 4px;
            }
            QSplitter::handle:vertical {
                height: 8px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        root.addWidget(self._build_header())
        root.addWidget(self._build_company_bar())

        self.tabs = GlowTabWidget(self)
        self.tabs.addTab(
            self._build_quick_tab(),
            QIcon(os.path.join(ASSETS_DIR, "testlab-tab-order.png")),
            TEST_LAB_TAB_ORDER_TEXT,
        )
        self.tabs.addTab(
            self._build_listing_quick_tab(),
            QIcon(os.path.join(ASSETS_DIR, "testlab-tab-listing.png")),
            TEST_LAB_TAB_LISTING_TEXT,
        )
        self.tabs.addTab(
            self._build_stage_quick_tab(),
            QIcon(os.path.join(ASSETS_DIR, "testlab-tab-order.png")),
            TEST_LAB_TAB_STAGE_TEXT,
        )
        self.tabs.addTab(
            self._build_diagnostics_quick_tab(),
            QIcon(os.path.join(ASSETS_DIR, "testlab-tab-diagnostics.png")),
            TEST_LAB_TAB_DIAGNOSTICS_TEXT,
        )
        self.tabs.addTab(
            self._build_release_tab(),
            QIcon(os.path.join(ASSETS_DIR, "testlab-tab-release.png")),
            TEST_LAB_TAB_BUILD_TEXT,
        )
        root.addWidget(self.tabs, 1)

        self._feature_windows: dict[str, QDialog] = {}
        self._global_log_lines: list[str] = []
        self.quick_order_log = None
        self.listing_order_log = None
        self.listing_sim_log = None
        self.stage_log = None
        self.diagnostics_output = None
        self.release_log_output = None

        self.load_companies()

    def _build_header(self) -> QFrame:
        frame = QFrame(self)
        frame.setObjectName("Card")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)

        txt = QVBoxLayout()
        title = QLabel(TEST_LAB_HEADER_TITLE)
        title.setObjectName("Title")
        sub = QLabel(TEST_LAB_HEADER_SUBTITLE)
        sub.setObjectName("Muted")
        txt.addWidget(title)
        txt.addWidget(sub)
        lay.addLayout(txt, 1)

        self.status_pill = QLabel(TEST_LAB_STATUS_READY_TEXT)
        self.status_pill.setObjectName("StatusPill")
        lay.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return frame

    def _build_company_bar(self) -> QFrame:
        frame = QFrame(self)
        frame.setObjectName("Card")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        lbl = QLabel(TEST_LAB_COMPANY_LABEL_TEXT)
        lbl.setObjectName("Muted")
        lay.addWidget(lbl)

        self.company_combo = QComboBox(self)
        self.company_combo.setMinimumWidth(380)
        self.company_combo.currentIndexChanged.connect(self._on_company_changed)
        lay.addWidget(self.company_combo)

        self.btn_refresh_companies = QPushButton(TEST_LAB_REFRESH_COMPANIES_BUTTON_TEXT, self)
        self.btn_refresh_companies.clicked.connect(self.load_companies)
        lay.addWidget(self.btn_refresh_companies)

        self.company_info = QLabel(TEST_LAB_NO_COMPANY_SELECTION_TEXT)
        self.company_info.setObjectName("Muted")
        lay.addWidget(self.company_info, 1)

        self._busy_widgets.extend([self.btn_refresh_companies, self.company_combo])
        return frame

    def _build_resizable_log_splitter(
        self,
        parent: QWidget,
        top_widget: QWidget,
        log_widget: QWidget,
        *,
        top_size: int = 430,
        log_size: int = 260,
    ) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Vertical, parent)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.addWidget(top_widget)
        splitter.addWidget(log_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([int(top_size), int(log_size)])
        return splitter

    def _populate_combo(self, combo: QComboBox | SwitchSelectWidget, values: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> None:
        combo.clear()
        for value, label in values:
            combo.addItem(str(label), str(value))

    def _build_lifecycle_preset_select(self, parent: QWidget) -> SwitchSelectWidget:
        select = SwitchSelectWidget(parent, multi=False, include_all=False, empty_text="Seçiniz")
        self._populate_combo(select, LIFECYCLE_PRESET_OPTIONS)
        select.setCurrentIndex(0)
        return select

    def _populate_text_combo(self, combo: QComboBox, values: tuple[str, ...]) -> None:
        combo.clear()
        for value in values:
            combo.addItem(str(value), str(value))

    def _apply_status_preset_to_controls(
        self,
        preset_combo: QComboBox | None,
        order_combo: QComboBox | None,
        shipment_combo: QComboBox | None,
    ) -> None:
        if preset_combo is None or order_combo is None or shipment_combo is None:
            return
        preset_key = str(preset_combo.currentData() or "").strip().lower()
        for key, _label, order_status, shipment_status in STATUS_PRESET_OPTIONS:
            if key != preset_key:
                continue
            order_combo.setCurrentText(order_status)
            shipment_combo.setCurrentText(shipment_status)
            return

    def _build_quick_tab(self) -> QWidget:
        page = QWidget(self)
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        quick_selector = QFrame(page)
        quick_selector.setObjectName("Card")
        quick_lay = QVBoxLayout(quick_selector)
        quick_lay.setContentsMargins(12, 10, 12, 10)
        quick_lay.setSpacing(8)

        selector_title = QLabel("Hızlı Erişim")
        selector_title.setObjectName("Title")
        selector_title.setStyleSheet("font-size:15px; font-weight:800; color:#0F172A;")
        selector_desc = QLabel("Kartlardan birini seç, ilgili test ekranı yeni pencerede açılsın.")
        selector_desc.setObjectName("Muted")
        quick_lay.addWidget(selector_title)
        quick_lay.addWidget(selector_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.btn_quick_order_sim = BadgeButton(
            "Sipariş Simülasyonu",
            icon_path=os.path.join(ASSETS_DIR, "testlab-tab-order.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.btn_quick_listing_order = BadgeButton(
            "Listingden Sipariş",
            icon_path=os.path.join(ASSETS_DIR, "testlab-tab-listing.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.btn_quick_order_sim.setMinimumHeight(100)
        self.btn_quick_listing_order.setMinimumHeight(100)
        self.btn_quick_order_sim.clicked.connect(self._open_order_sim_window)
        self.btn_quick_listing_order.clicked.connect(self._open_listing_order_window)
        self.btn_quick_order_sim.setActive(True)
        self.btn_quick_listing_order.setActive(True)
        cards_row.addWidget(self.btn_quick_order_sim)
        cards_row.addWidget(self.btn_quick_listing_order)
        cards_row.addStretch(1)
        quick_lay.addLayout(cards_row)
        root.addWidget(quick_selector, 0, Qt.AlignmentFlag.AlignTop)
        root.addStretch(1)
        return page

    def _build_order_simulation_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        order_card = QFrame(page)
        order_card.setObjectName("Card")
        order_lay = QVBoxLayout(order_card)
        order_lay.setContentsMargins(18, 16, 18, 16)
        order_lay.setSpacing(14)

        order_title = QLabel("Sipariş Simülasyonu")
        order_title.setObjectName("Title")
        order_title.setStyleSheet("font-size:16px; font-weight:800; color:#0F172A;")
        order_desc = QLabel("Rastgele sipariş akışlarını anında simüle et")
        order_desc.setObjectName("Muted")
        order_desc.setWordWrap(True)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        title_col.addWidget(order_title)
        title_col.addWidget(order_desc)
        header_row.addLayout(title_col, 1)
        order_lay.addLayout(header_row)

        controls_grid = QGridLayout()
        controls_grid.setContentsMargins(0, 0, 0, 0)
        controls_grid.setHorizontalSpacing(12)
        controls_grid.setVerticalSpacing(6)
        for col in range(4):
            controls_grid.setColumnStretch(col, 0)
        controls_grid.setColumnStretch(4, 1)

        count_label = QLabel("Sipariş adedi")
        count_label.setObjectName("Muted")
        controls_grid.addWidget(count_label, 0, 0)
        self.quick_order_count = NumberStepper(order_card, minimum=1, maximum=300, step=1)
        self.quick_order_count.setValue(3)
        self.quick_order_count.setMinimumWidth(190)
        self.quick_order_count.setMaximumWidth(220)
        controls_grid.addWidget(self.quick_order_count, 1, 0)

        lines_label = QLabel("Satır / sipariş")
        lines_label.setObjectName("Muted")
        controls_grid.addWidget(lines_label, 0, 1)
        self.quick_lines_per_order = NumberStepper(order_card, minimum=1, maximum=30, step=1)
        self.quick_lines_per_order.setValue(2)
        self.quick_lines_per_order.setMinimumWidth(190)
        self.quick_lines_per_order.setMaximumWidth(220)
        controls_grid.addWidget(self.quick_lines_per_order, 1, 1)

        lifecycle_label = QLabel("Lifecycle")
        lifecycle_label.setObjectName("Muted")
        controls_grid.addWidget(lifecycle_label, 0, 2)
        self.quick_lifecycle_preset = self._build_lifecycle_preset_select(order_card)
        self.quick_lifecycle_preset.setMinimumWidth(210)
        self.quick_lifecycle_preset.setMaximumWidth(260)
        controls_grid.addWidget(self.quick_lifecycle_preset, 1, 2)

        self.btn_sim_orders = QPushButton("Sipariş gelişi simüle et", order_card)
        self.btn_sim_orders.setObjectName("PrimaryBtn")
        self.btn_sim_orders.setMinimumWidth(240)
        self.btn_sim_orders.setMaximumWidth(280)
        self.btn_sim_orders.setMinimumHeight(46)
        self.btn_sim_orders.clicked.connect(self.simulate_orders)
        controls_grid.addWidget(self.btn_sim_orders, 1, 3)
        order_lay.addLayout(controls_grid)

        log_card = QFrame(page)
        log_card.setObjectName("Card")
        log_lay = QVBoxLayout(log_card)
        log_lay.setContentsMargins(14, 12, 14, 14)
        log_lay.setSpacing(10)
        log_top = QHBoxLayout()
        quick_log_title = QLabel("Canlı Log")
        quick_log_title.setObjectName("Title")
        quick_log_title.setStyleSheet("font-size:14px; font-weight:800; color:#0F172A;")
        log_top.addWidget(quick_log_title)
        log_top.addStretch(1)
        self.btn_clear_quick_order_log = QPushButton("Log temizle", log_card)
        self.btn_clear_quick_order_log.clicked.connect(lambda: self.quick_order_log.clear())
        log_top.addWidget(self.btn_clear_quick_order_log)
        log_lay.addLayout(log_top)

        self.quick_order_log = QTextEdit(log_card)
        self.quick_order_log.setReadOnly(True)
        self.quick_order_log.setPlaceholderText("Sipariş simülasyonu akışı burada görünür...")
        self.quick_order_log.setMinimumHeight(140)
        log_lay.addWidget(self.quick_order_log)

        splitter = self._build_resizable_log_splitter(
            page,
            order_card,
            log_card,
            top_size=230,
            log_size=560,
        )
        root.addWidget(splitter, 1)

        self._busy_widgets.extend([self.btn_sim_orders, self.btn_clear_quick_order_log])
        return page

    def _build_listing_order_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        page_root = QVBoxLayout(page)
        page_root.setContentsMargins(4, 4, 4, 4)
        page_root.setSpacing(10)

        work_area = QHBoxLayout()
        work_area.setContentsMargins(0, 0, 0, 0)
        work_area.setSpacing(10)

        controls = QFrame(page)
        controls.setObjectName("Card")
        controls.setFixedWidth(280)
        controls_lay = QVBoxLayout(controls)
        controls_lay.setContentsMargins(12, 12, 12, 12)
        controls_lay.setSpacing(10)

        title = QLabel("Listingden Sipariş")
        title.setObjectName("Title")
        title.setStyleSheet("font-size:17px; font-weight:800; color:#0F172A;")
        controls_lay.addWidget(title)

        company_title = QLabel("Şirket")
        company_title.setStyleSheet("font-weight:800; color:#0F172A;")
        controls_lay.addWidget(company_title)
        self.listing_company_label = QLabel("Seçili şirket yükleniyor...")
        self.listing_company_label.setObjectName("Muted")
        self.listing_company_label.setStyleSheet(
            "padding: 9px 10px; background:#FFFFFF; border:1px solid #D8DEE8; border-radius:8px; color:#0F172A;"
        )
        controls_lay.addWidget(self.listing_company_label)

        search_title = QLabel("Arama")
        search_title.setStyleSheet("font-weight:800; color:#0F172A;")
        controls_lay.addWidget(search_title)
        self.listing_search = QLineEdit(controls)
        self.listing_search.setPlaceholderText("Başlık, stok kodu, ürün id, barkod...")
        self.listing_search.textChanged.connect(lambda _=None: self._apply_listing_order_filters())
        controls_lay.addWidget(self.listing_search)

        stock_filter_title = QLabel("Stok bağlantısı")
        stock_filter_title.setStyleSheet("font-weight:800; color:#0F172A;")
        controls_lay.addWidget(stock_filter_title)
        self.listing_stock_filter = SwitchSelectWidget(controls, multi=False, include_all=False, empty_text="Tümü")
        self._populate_combo(
            self.listing_stock_filter,
            [
                ("all", "Tümü"),
                ("linked", "Stok bağlı"),
                ("missing", "Stok yok"),
            ],
        )
        self.listing_stock_filter.setCurrentIndex(0)
        self.listing_stock_filter.currentIndexChanged.connect(lambda _=0: self._apply_listing_order_filters())
        controls_lay.addWidget(self.listing_stock_filter)

        self.listing_positive_stock_only = QCheckBox("Sadece pozitif stok", controls)
        self.listing_positive_stock_only.stateChanged.connect(lambda _=0: self._apply_listing_order_filters())
        controls_lay.addWidget(self.listing_positive_stock_only)

        count_title = QLabel("Üretilecek sipariş sayısı")
        count_title.setStyleSheet("font-weight:800; color:#0F172A;")
        controls_lay.addWidget(count_title)
        self.listing_order_count = NumberStepper(controls, minimum=1, maximum=10, step=1)
        self.listing_order_count.setValue(1)
        controls_lay.addWidget(self.listing_order_count)
        hint = QLabel("1 - 10 arası")
        hint.setObjectName("Muted")
        controls_lay.addWidget(hint)

        lifecycle_title = QLabel("Lifecycle")
        lifecycle_title.setStyleSheet("font-weight:800; color:#0F172A;")
        controls_lay.addWidget(lifecycle_title)
        self.listing_lifecycle_preset = self._build_lifecycle_preset_select(controls)
        controls_lay.addWidget(self.listing_lifecycle_preset)

        self.btn_sim_orders_from_listings = QPushButton("Seçili ilandan sipariş oluştur", controls)
        self.btn_sim_orders_from_listings.setObjectName("PrimaryBtn")
        self.btn_sim_orders_from_listings.clicked.connect(self.simulate_orders_from_listings)
        controls_lay.addWidget(self.btn_sim_orders_from_listings)

        self.btn_verify_listing_order_flow = QPushButton("Smoke doğrula", controls)
        self.btn_verify_listing_order_flow.clicked.connect(self.verify_listing_order_flow)
        controls_lay.addWidget(self.btn_verify_listing_order_flow)

        controls_lay.addStretch(1)
        self.btn_listing_filter_clear = QPushButton("Temizle", controls)
        self.btn_listing_filter_clear.clicked.connect(self._clear_listing_order_filters)
        controls_lay.addWidget(self.btn_listing_filter_clear)

        main_panel = QFrame(page)
        main_panel.setObjectName("Card")
        main_lay = QVBoxLayout(main_panel)
        main_lay.setContentsMargins(12, 12, 12, 12)
        main_lay.setSpacing(10)

        metric_row = QHBoxLayout()
        metric_row.setSpacing(10)
        self.listing_metric_total = self._build_listing_metric_card("0", "Toplam ilan", main_panel)
        self.listing_metric_selected = self._build_listing_metric_card("0", "Seçili ilan", main_panel)
        self.listing_metric_linked = self._build_listing_metric_card("0", "Stok bağlı", main_panel)
        self.listing_metric_missing = self._build_listing_metric_card("0", "Stok yok", main_panel)
        for metric in (
            self.listing_metric_total,
            self.listing_metric_selected,
            self.listing_metric_linked,
            self.listing_metric_missing,
        ):
            metric_row.addWidget(metric["frame"])
        metric_row.addStretch(1)
        self.btn_load_listings = QPushButton("Yenile", main_panel)
        self.btn_load_listings.clicked.connect(self.load_listings)
        metric_row.addWidget(self.btn_load_listings)
        main_lay.addLayout(metric_row)

        self.listing_cards_scroll = QScrollArea(main_panel)
        self.listing_cards_scroll.setWidgetResizable(True)
        self.listing_cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.listing_cards_scroll.setObjectName("ListingCardsScroll")
        self.listing_cards_host = QWidget(self.listing_cards_scroll)
        self.listing_cards_layout = QVBoxLayout(self.listing_cards_host)
        self.listing_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.listing_cards_layout.setSpacing(6)
        self.listing_cards_layout.addStretch(1)
        self.listing_cards_scroll.setWidget(self.listing_cards_host)
        main_lay.addWidget(self.listing_cards_scroll, 1)

        footer_row = QHBoxLayout()
        footer_row.addStretch(1)
        self.btn_listing_selection_toggle = SelectClearToggleButton(
            select_text="Tümünü Seç",
            clear_text="Seçimi Kaldır",
            parent=main_panel,
        )
        self.btn_listing_selection_toggle.actionRequested.connect(self._on_listing_selection_toggle_action)
        footer_row.addWidget(self.btn_listing_selection_toggle)
        main_lay.addLayout(footer_row)

        work_area.addWidget(controls)
        work_area.addWidget(main_panel, 1)
        page_root.addLayout(work_area, 1)

        log_card = QFrame(page)
        log_card.setObjectName("Card")
        log_lay = QVBoxLayout(log_card)
        log_lay.setContentsMargins(10, 10, 10, 10)
        log_lay.setSpacing(6)
        log_top = QHBoxLayout()
        log_top.addWidget(QLabel("Canlı Log"))
        log_top.addStretch(1)
        self.btn_clear_listing_order_log = QPushButton("Log temizle", log_card)
        self.btn_clear_listing_order_log.clicked.connect(lambda: self.listing_order_log.clear())
        log_top.addWidget(self.btn_clear_listing_order_log)
        log_lay.addLayout(log_top)

        self.listing_order_log = QTextEdit(log_card)
        self.listing_order_log.setReadOnly(True)
        self.listing_order_log.setPlaceholderText("Listingden sipariş simülasyonu akışı burada görünür...")
        self.listing_order_log.setFixedHeight(118)
        log_lay.addWidget(self.listing_order_log)
        page_root.addWidget(log_card, 0)

        self._busy_widgets.extend([
            self.btn_load_listings,
            self.btn_listing_selection_toggle,
            self.btn_sim_orders_from_listings,
            self.btn_verify_listing_order_flow,
            self.listing_search,
            self.listing_stock_filter,
            self.listing_positive_stock_only,
            self.btn_listing_filter_clear,
            self.btn_clear_listing_order_log,
        ])
        self._update_listing_company_label()
        self._sync_listing_selection_toggle_button()
        return page

    def _build_listing_metric_card(self, value: str, label: str, parent: QWidget) -> dict:
        frame = QFrame(parent)
        frame.setObjectName("MetricCard")
        frame.setMinimumWidth(150)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(2)
        value_label = QLabel(str(value), frame)
        value_label.setStyleSheet("font-size:20px; font-weight:900; color:#0F172A;")
        label_widget = QLabel(str(label), frame)
        label_widget.setObjectName("Muted")
        lay.addWidget(value_label)
        lay.addWidget(label_widget)
        return {"frame": frame, "value": value_label, "label": label_widget}

    def _set_metric_value(self, metric: dict | None, value: int) -> None:
        if not metric:
            return
        label = metric.get("value")
        if label is not None:
            label.setText(str(int(value)))

    def _update_listing_company_label(self) -> None:
        label = getattr(self, "listing_company_label", None)
        if label is None:
            return
        company_pk = self._selected_company_pk()
        current = ""
        idx = self.company_combo.currentIndex() if getattr(self, "company_combo", None) is not None else -1
        if idx >= 0:
            current = self.company_combo.currentText()
        label.setText(current or (f"Şirket #{company_pk}" if company_pk is not None else "Seçim yok"))

    def _clear_listing_order_filters(self) -> None:
        if getattr(self, "listing_search", None) is not None:
            self.listing_search.clear()
        if getattr(self, "listing_stock_filter", None) is not None:
            self.listing_stock_filter.setCurrentIndex(0)
        if getattr(self, "listing_positive_stock_only", None) is not None:
            self.listing_positive_stock_only.setChecked(False)
        self._apply_listing_order_filters()

    def _listing_has_stock_link(self, item: dict) -> bool:
        if bool(item.get("stock_linked")):
            return True
        for row in list(item.get("stock_items") or []):
            if not isinstance(row, dict):
                continue
            try:
                if int(row.get("stock_item_id")) > 0:
                    return True
            except Exception:
                continue
        return False

    def _listing_item_matches_filters(self, item: dict) -> bool:
        text = ""
        if getattr(self, "listing_search", None) is not None:
            text = str(self.listing_search.text() or "").strip().casefold()
        if text:
            haystack = " ".join(
                str(item.get(key) or "")
                for key in ("title", "stock_code", "product_id", "barcode", "brand")
            ).casefold()
            if text not in haystack:
                return False

        stock_mode = "all"
        if getattr(self, "listing_stock_filter", None) is not None:
            stock_mode = str(self.listing_stock_filter.currentData() or "all")
        linked = self._listing_has_stock_link(item)
        if stock_mode == "linked" and not linked:
            return False
        if stock_mode == "missing" and linked:
            return False

        if getattr(self, "listing_positive_stock_only", None) is not None and self.listing_positive_stock_only.isChecked():
            try:
                qty = float(item.get("quantity") or 0)
            except Exception:
                qty = 0.0
            if qty <= 0:
                return False
        return True

    def _apply_listing_order_filters(self) -> None:
        if not hasattr(self, "listing_cards_layout"):
            return
        filtered = [item for item in self._listing_items_cache if self._listing_item_matches_filters(item)]
        self._populate_listing_cards(filtered)

    def _stock_status_text(self, item: dict) -> tuple[str, str, str]:
        if self._listing_has_stock_link(item):
            ids = list(item.get("stock_item_ids") or [])
            detail = f"Stock Item: {', '.join(str(i) for i in ids[:3])}" if ids else "Stock Item bağlı"
            return "Stok bağlı", detail, "ok"
        return "Stok yok", "Eşleşen stok kartı bulunamadı", "warn"

    def _make_listing_card(self, item: dict) -> dict:
        frame = QFrame(self.listing_cards_host)
        frame.setObjectName("ListingOrderRow")
        frame.setProperty("selected", False)
        frame.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        checkbox = QCheckBox(frame)
        checkbox.setFixedWidth(28)
        checkbox.stateChanged.connect(lambda _=0: self._on_listing_card_checked(frame, checkbox))
        lay.addWidget(checkbox)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title = QLabel(str(item.get("title") or item.get("product_id") or "-"), frame)
        title.setStyleSheet("font-weight:800; color:#0F172A;")
        title.setWordWrap(False)
        meta = QLabel(
            f"Stok Kodu: {item.get('stock_code') or '-'}    |    Ürün ID: {item.get('product_id') or '-'}",
            frame,
        )
        meta.setObjectName("Muted")
        title_col.addWidget(title)
        title_col.addWidget(meta)
        lay.addLayout(title_col, 1)

        for heading, value, width in (
            ("Barkod", item.get("barcode") or "-", 150),
            ("Qty", item.get("quantity") if item.get("quantity") not in (None, "") else "-", 70),
            ("Marka", item.get("brand") or "-", 130),
        ):
            col = QVBoxLayout()
            col.setSpacing(4)
            h = QLabel(str(heading), frame)
            h.setObjectName("Muted")
            v = QLabel(str(value), frame)
            v.setStyleSheet("font-weight:700; color:#0F172A;")
            v.setWordWrap(False)
            col.addWidget(h)
            col.addWidget(v)
            wrap = QWidget(frame)
            wrap.setFixedWidth(width)
            wrap.setLayout(col)
            lay.addWidget(wrap)

        status, detail, tone = self._stock_status_text(item)
        status_col = QVBoxLayout()
        status_col.setSpacing(5)
        badge = QLabel(status, frame)
        if tone == "ok":
            badge.setStyleSheet("background:#DCFCE7; color:#166534; border:1px solid #BBF7D0; border-radius:7px; padding:4px 8px; font-weight:900;")
        else:
            badge.setStyleSheet("background:#FFEDD5; color:#C2410C; border:1px solid #FED7AA; border-radius:7px; padding:4px 8px; font-weight:900;")
        detail_label = QLabel(detail, frame)
        detail_label.setObjectName("Muted")
        status_col.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
        status_col.addWidget(detail_label)
        status_wrap = QWidget(frame)
        status_wrap.setFixedWidth(190)
        status_wrap.setLayout(status_col)
        lay.addWidget(status_wrap)

        row = {"frame": frame, "checkbox": checkbox, "item": item}
        frame.mousePressEvent = lambda _event, r=row: self._toggle_listing_card(r)
        return row

    def _on_listing_card_checked(self, frame: QFrame, checkbox: QCheckBox) -> None:
        frame.setProperty("selected", checkbox.isChecked())
        frame.style().unpolish(frame)
        frame.style().polish(frame)
        self._sync_listing_selection_toggle_button()

    def _toggle_listing_card(self, row: dict) -> None:
        checkbox = row.get("checkbox")
        if checkbox is None:
            return
        checkbox.setChecked(not checkbox.isChecked())

    def _populate_listing_cards(self, items: list[dict]) -> None:
        layout = getattr(self, "listing_cards_layout", None)
        if layout is None:
            return
        while layout.count() > 0:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._listing_row_widgets = []
        for item in items:
            row = self._make_listing_card(item)
            self._listing_row_widgets.append(row)
            layout.addWidget(row["frame"])
        if not items:
            empty = QLabel("Bu filtrelerle gösterilecek ilan yok.", self.listing_cards_host)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setObjectName("Muted")
            empty.setMinimumHeight(160)
            layout.addWidget(empty)
        layout.addStretch(1)
        self._sync_listing_selection_toggle_button()

    def _build_listing_quick_tab(self) -> QWidget:
        page = QWidget(self)
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        quick_selector = QFrame(page)
        quick_selector.setObjectName("Card")
        quick_lay = QVBoxLayout(quick_selector)
        quick_lay.setContentsMargins(12, 10, 12, 10)
        quick_lay.setSpacing(8)

        selector_title = QLabel("Hızlı Erişim")
        selector_title.setObjectName("Title")
        selector_title.setStyleSheet("font-size:15px; font-weight:800; color:#0F172A;")
        selector_desc = QLabel("Listing test ekranını yeni pencerede aç.")
        selector_desc.setObjectName("Muted")
        quick_lay.addWidget(selector_title)
        quick_lay.addWidget(selector_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.btn_quick_listing_sim = BadgeButton(
            "Listing Simülasyonu",
            icon_path=os.path.join(ASSETS_DIR, "testlab-tab-listing.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.btn_quick_listing_sim.setMinimumHeight(100)
        self.btn_quick_listing_sim.clicked.connect(self._open_listing_sim_window)
        self.btn_quick_listing_sim.setActive(True)
        cards_row.addWidget(self.btn_quick_listing_sim)
        cards_row.addStretch(1)
        quick_lay.addLayout(cards_row)

        root.addWidget(quick_selector, 0, Qt.AlignmentFlag.AlignTop)
        root.addStretch(1)
        return page

    def _build_listing_simulation_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        listing_card = QFrame(page)
        listing_card.setObjectName("Card")
        listing_lay = QVBoxLayout(listing_card)
        listing_lay.setContentsMargins(18, 16, 18, 16)
        listing_lay.setSpacing(14)

        listing_title = QLabel("Listing Simülasyonu")
        listing_title.setObjectName("Title")
        listing_title.setStyleSheet("font-size:16px; font-weight:800; color:#0F172A;")
        listing_desc = QLabel("Yeni ilan akışlarını cache/DB üzerinden test et")
        listing_desc.setObjectName("Muted")
        header_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        title_col.addWidget(listing_title)
        title_col.addWidget(listing_desc)
        header_row.addLayout(title_col, 1)
        listing_lay.addLayout(header_row)

        lgrid = QGridLayout()
        lgrid.setContentsMargins(0, 0, 0, 0)
        lgrid.setHorizontalSpacing(14)
        count_lbl = QLabel("Listing adedi")
        count_lbl.setObjectName("Muted")
        lgrid.addWidget(count_lbl, 0, 0)
        self.quick_listing_count = NumberStepper(listing_card, minimum=1, maximum=1000, step=1)
        self.quick_listing_count.setValue(10)
        self.quick_listing_count.setMinimumWidth(190)
        self.quick_listing_count.setMaximumWidth(220)
        lgrid.addWidget(self.quick_listing_count, 1, 0)
        self.btn_sim_listings = QPushButton("Listing gelişi simüle et", listing_card)
        self.btn_sim_listings.setObjectName("PrimaryBtn")
        self.btn_sim_listings.setMinimumHeight(46)
        self.btn_sim_listings.setMinimumWidth(260)
        self.btn_sim_listings.clicked.connect(self.simulate_listings)
        lgrid.addWidget(self.btn_sim_listings, 1, 1)
        lgrid.setColumnStretch(2, 1)
        listing_lay.addLayout(lgrid)

        log_card = QFrame(page)
        log_card.setObjectName("Card")
        log_lay = QVBoxLayout(log_card)
        log_lay.setContentsMargins(10, 10, 10, 10)
        log_lay.setSpacing(6)
        log_top = QHBoxLayout()
        log_top.addWidget(QLabel("Canlı Log"))
        log_top.addStretch(1)
        self.btn_clear_listing_sim_log = QPushButton("Log temizle", log_card)
        self.btn_clear_listing_sim_log.clicked.connect(lambda: self.listing_sim_log.clear())
        log_top.addWidget(self.btn_clear_listing_sim_log)
        log_lay.addLayout(log_top)

        self.listing_sim_log = QTextEdit(log_card)
        self.listing_sim_log.setReadOnly(True)
        self.listing_sim_log.setPlaceholderText("Listing simülasyonu akışı burada görünür...")
        self.listing_sim_log.setMinimumHeight(150)
        log_lay.addWidget(self.listing_sim_log)

        splitter = self._build_resizable_log_splitter(
            page,
            listing_card,
            log_card,
            top_size=210,
            log_size=560,
        )
        root.addWidget(splitter, 1)

        self._busy_widgets.extend([self.btn_sim_listings, self.btn_clear_listing_sim_log])
        return page

    def _build_stage_quick_tab(self) -> QWidget:
        page = QWidget(self)
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        selector = QFrame(page)
        selector.setObjectName("Card")
        lay = QVBoxLayout(selector)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel("Trendyol Stage")
        title.setObjectName("Title")
        title.setStyleSheet("font-size:15px; font-weight:800; color:#0F172A;")
        desc = QLabel(
            "Gerçek uygulama akışlarını sınamak için Stage'de sipariş ve iade yaşam döngüsü üret. "
            "Production hesapları kod seviyesinde engellenir."
        )
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(desc)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.btn_quick_stage_lab = BadgeButton(
            "Stage Senaryoları",
            icon_path=os.path.join(ASSETS_DIR, "testlab-tab-order.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.btn_quick_stage_lab.setMinimumHeight(100)
        self.btn_quick_stage_lab.setActive(True)
        self.btn_quick_stage_lab.clicked.connect(self._open_stage_window)
        cards.addWidget(self.btn_quick_stage_lab)
        cards.addStretch(1)
        lay.addLayout(cards)

        root.addWidget(selector, 0, Qt.AlignmentFlag.AlignTop)
        root.addStretch(1)
        return page

    def _build_stage_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        controls = QFrame(page)
        controls.setObjectName("Card")
        controls_lay = QVBoxLayout(controls)
        controls_lay.setContentsMargins(16, 14, 16, 14)
        controls_lay.setSpacing(12)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title = QLabel("Trendyol Stage Senaryo Laboratuvarı")
        title.setObjectName("Title")
        title.setStyleSheet("font-size:17px; font-weight:800; color:#0F172A;")
        subtitle = QLabel(
            "Test verisini Stage'de üretir; sipariş/iade okuma ve onaylama için uygulamanın gerçek domain yollarını kullanır."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        self.stage_account_pill = QLabel("Stage hesabı bekleniyor")
        self.stage_account_pill.setObjectName("StatusPill")
        header.addWidget(self.stage_account_pill, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls_lay.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)

        listing_label = QLabel("Stage test ürünü veya onaylı ilan")
        listing_label.setObjectName("Muted")
        grid.addWidget(listing_label, 0, 0)
        self.stage_listing_combo = QComboBox(controls)
        self.stage_listing_combo.setMinimumWidth(360)
        grid.addWidget(self.stage_listing_combo, 1, 0, 1, 2)

        qty_label = QLabel("Adet")
        qty_label.setObjectName("Muted")
        grid.addWidget(qty_label, 0, 2)
        self.stage_quantity = NumberStepper(controls, minimum=1, maximum=20, step=1)
        self.stage_quantity.setValue(1)
        self.stage_quantity.setMinimumWidth(150)
        grid.addWidget(self.stage_quantity, 1, 2)

        self.btn_stage_create_order = QPushButton("Stage siparişi oluştur", controls)
        self.btn_stage_create_order.setObjectName("PrimaryBtn")
        self.btn_stage_create_order.setMinimumHeight(44)
        self.btn_stage_create_order.clicked.connect(self.create_stage_order)
        grid.addWidget(self.btn_stage_create_order, 1, 3)

        order_label = QLabel("Stage siparişi")
        order_label.setObjectName("Muted")
        grid.addWidget(order_label, 2, 0)
        self.stage_order_combo = QComboBox(controls)
        self.stage_order_combo.setMinimumWidth(360)
        grid.addWidget(self.stage_order_combo, 3, 0, 1, 2)

        status_label = QLabel("Hedef durum")
        status_label.setObjectName("Muted")
        grid.addWidget(status_label, 2, 2)
        self.stage_status_combo = QComboBox(controls)
        for value in ("Shipped", "AtCollectionPoint", "Delivered", "UnDelivered", "Returned"):
            self.stage_status_combo.addItem(value, value)
        grid.addWidget(self.stage_status_combo, 3, 2)

        self.btn_stage_advance_order = QPushButton("Siparişi ilerlet", controls)
        self.btn_stage_advance_order.clicked.connect(self.advance_stage_order)
        grid.addWidget(self.btn_stage_advance_order, 3, 3)

        self.btn_stage_create_return = QPushButton("Bu siparişten iade oluştur", controls)
        self.btn_stage_create_return.clicked.connect(self.create_stage_return)
        grid.addWidget(self.btn_stage_create_return, 4, 0, 1, 2)

        claim_label = QLabel("Stage iadesi")
        claim_label.setObjectName("Muted")
        grid.addWidget(claim_label, 5, 0)
        self.stage_claim_combo = QComboBox(controls)
        self.stage_claim_combo.setMinimumWidth(360)
        grid.addWidget(self.stage_claim_combo, 6, 0, 1, 2)

        self.btn_stage_waiting_action = QPushButton("WaitingInAction yap", controls)
        self.btn_stage_waiting_action.clicked.connect(self.advance_stage_claim)
        grid.addWidget(self.btn_stage_waiting_action, 6, 2)

        self.btn_stage_approve_return = QPushButton("Uygulama aksiyonuyla onayla", controls)
        self.btn_stage_approve_return.clicked.connect(self.approve_stage_return)
        grid.addWidget(self.btn_stage_approve_return, 6, 3)

        self.btn_stage_full_lifecycle = QPushButton(
            "Tam yaşam döngüsünü çalıştır: sipariş → teslimat → iade → onay",
            controls,
        )
        self.btn_stage_full_lifecycle.setObjectName("PrimaryBtn")
        self.btn_stage_full_lifecycle.setMinimumHeight(48)
        self.btn_stage_full_lifecycle.clicked.connect(self.run_stage_return_lifecycle)
        grid.addWidget(self.btn_stage_full_lifecycle, 7, 0, 1, 3)

        self.btn_stage_refresh = QPushButton("Stage bağlamını yenile", controls)
        self.btn_stage_refresh.clicked.connect(self.load_stage_context)
        grid.addWidget(self.btn_stage_refresh, 7, 3)

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)
        controls_lay.addLayout(grid)

        log_card = QFrame(page)
        log_card.setObjectName("Card")
        log_lay = QVBoxLayout(log_card)
        log_lay.setContentsMargins(12, 10, 12, 12)
        log_lay.setSpacing(8)
        log_header = QHBoxLayout()
        log_title = QLabel("Stage Kanıt Günlüğü")
        log_title.setObjectName("Title")
        log_title.setStyleSheet("font-size:14px; font-weight:800; color:#0F172A;")
        log_header.addWidget(log_title)
        log_header.addStretch(1)
        self.btn_clear_stage_log = QPushButton("Log temizle", log_card)
        self.btn_clear_stage_log.clicked.connect(lambda: self.stage_log.clear())
        log_header.addWidget(self.btn_clear_stage_log)
        log_lay.addLayout(log_header)

        self.stage_log = QTextEdit(log_card)
        self.stage_log.setReadOnly(True)
        self.stage_log.setPlaceholderText("Stage istekleri, DB geri okumaları ve doğrulama adımları burada görünür...")
        self.stage_log.setMinimumHeight(180)
        log_lay.addWidget(self.stage_log)

        splitter = self._build_resizable_log_splitter(
            page,
            controls,
            log_card,
            top_size=390,
            log_size=420,
        )
        root.addWidget(splitter, 1)

        self._busy_widgets.extend(
            [
                self.stage_listing_combo,
                self.stage_quantity,
                self.btn_stage_create_order,
                self.stage_order_combo,
                self.stage_status_combo,
                self.btn_stage_advance_order,
                self.btn_stage_create_return,
                self.stage_claim_combo,
                self.btn_stage_waiting_action,
                self.btn_stage_approve_return,
                self.btn_stage_full_lifecycle,
                self.btn_stage_refresh,
                self.btn_clear_stage_log,
            ]
        )
        return page

    def _build_release_tab(self) -> QWidget:
        page = QWidget(self)
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        controls = QFrame(page)
        controls.setObjectName("Card")
        grid = QGridLayout(controls)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        title = QLabel("Tek Tuş Release")
        title.setObjectName("Title")
        title.setStyleSheet("font-size:16px; font-weight:800; color:#0F172A;")
        subtitle = QLabel(
            "Butona bastığında APP_VERSION build edilir, release repo güncellenir, tag yenilenir ve setup asset'i GitHub Release'e yüklenir."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        grid.addWidget(title, 0, 0, 1, 3)
        grid.addWidget(subtitle, 1, 0, 1, 3)

        grid.addWidget(QLabel("Release sürüm"), 2, 0)
        self.release_version_value = QLabel(str(APP_VERSION or "0.1.0"))
        self.release_version_value.setStyleSheet(
            "font-weight:700; color:#0F172A; padding:6px 10px; "
            "background:#FFFFFF; border:1px solid rgba(15,23,42,0.20); border-radius:8px;"
        )
        grid.addWidget(self.release_version_value, 2, 1, 1, 2)

        self.release_stage_label = QLabel("Hazır")
        self.release_stage_label.setObjectName("Muted")
        grid.addWidget(self.release_stage_label, 3, 0, 1, 3)

        button_row = QHBoxLayout()
        button_row.setSpacing(12)
        self.btn_build_release = CircularProgressButton("RELEASE", controls, size_scale=1.05)
        self.btn_build_release.clicked.connect(self.start_release_build)
        button_row.addWidget(self.btn_build_release, 0, Qt.AlignmentFlag.AlignLeft)

        self.btn_open_last_release_dir = QPushButton("Son Çıkışı Aç", controls)
        self.btn_open_last_release_dir.clicked.connect(self._open_last_release_output_dir)
        self.btn_open_last_release_dir.setEnabled(False)
        button_row.addWidget(self.btn_open_last_release_dir, 0, Qt.AlignmentFlag.AlignLeft)

        button_row.addStretch(1)
        grid.addLayout(button_row, 4, 0, 1, 3)

        self.release_output_hint = QLabel("Çıktı klasörü: Desktop/os-release | Repo: Desktop/OrderScout-releases")
        self.release_output_hint.setObjectName("Muted")
        self.release_output_hint.setWordWrap(True)
        grid.addWidget(self.release_output_hint, 5, 0, 1, 3)

        root.addWidget(controls, 0, Qt.AlignmentFlag.AlignTop)

        log_card = QFrame(page)
        log_card.setObjectName("Card")
        log_lay = QVBoxLayout(log_card)
        log_lay.setContentsMargins(10, 10, 10, 10)
        log_lay.setSpacing(6)

        log_top = QHBoxLayout()
        log_top.addWidget(QLabel("Canlı Build Log"))
        log_top.addStretch(1)
        self.btn_clear_release_log = QPushButton("Log temizle", log_card)
        self.btn_clear_release_log.clicked.connect(
            lambda: self.release_log_output.clear() if self.release_log_output is not None else None
        )
        log_top.addWidget(self.btn_clear_release_log)
        log_lay.addLayout(log_top)

        self.release_log_output = QTextEdit(log_card)
        self.release_log_output.setReadOnly(True)
        self.release_log_output.setPlaceholderText(
            "Build akışında gelen canlı komut çıktıları burada görünür."
        )
        log_lay.addWidget(self.release_log_output, 1)
        root.addWidget(log_card, 1)

        self._busy_widgets.extend(
            [
                self.btn_build_release,
                self.btn_open_last_release_dir,
                self.btn_clear_release_log,
            ]
        )
        return page

    def _build_diagnostics_quick_tab(self) -> QWidget:
        page = QWidget(self)
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        quick_selector = QFrame(page)
        quick_selector.setObjectName("Card")
        quick_lay = QVBoxLayout(quick_selector)
        quick_lay.setContentsMargins(12, 10, 12, 10)
        quick_lay.setSpacing(8)

        selector_title = QLabel("Hızlı Erişim")
        selector_title.setObjectName("Title")
        selector_title.setStyleSheet("font-size:15px; font-weight:800; color:#0F172A;")
        selector_desc = QLabel("Tanı/Test araçlarını yeni pencerede aç.")
        selector_desc.setObjectName("Muted")
        quick_lay.addWidget(selector_title)
        quick_lay.addWidget(selector_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.btn_quick_healthcheck = BadgeButton(
            "Domain Healthcheck",
            icon_path=os.path.join(ASSETS_DIR, "testlab-tab-diagnostics.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.btn_quick_healthcheck.setMinimumHeight(100)
        self.btn_quick_healthcheck.clicked.connect(self._open_diagnostics_window)
        self.btn_quick_healthcheck.setActive(True)
        cards_row.addWidget(self.btn_quick_healthcheck)
        cards_row.addStretch(1)
        quick_lay.addLayout(cards_row)

        root.addWidget(quick_selector, 0, Qt.AlignmentFlag.AlignTop)
        root.addStretch(1)
        return page

    def _build_diagnostics_page(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        controls = QFrame(page)
        controls.setObjectName("Card")
        controls_lay = QVBoxLayout(controls)
        controls_lay.setContentsMargins(14, 8, 14, 8)
        controls_lay.setSpacing(7)
        controls_lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        test_title = QLabel("Yerel test suite")
        test_title.setStyleSheet("font-size:16px; font-weight:900; color:#0F172A;")
        controls_lay.addWidget(test_title)

        test_grid = QGridLayout()
        test_grid.setHorizontalSpacing(12)
        test_grid.setVerticalSpacing(8)
        test_grid.setColumnStretch(1, 1)
        test_grid.setColumnStretch(3, 1)

        test_grid.addWidget(QLabel("Pattern"), 0, 0)
        self.test_pattern = QLineEdit(controls)
        self.test_pattern.setText("test_*.py")
        test_grid.addWidget(self.test_pattern, 0, 1)

        test_grid.addWidget(QLabel("Timeout (sec)"), 0, 2)
        self.test_timeout = NumberStepper(controls, minimum=30, maximum=1800, step=10)
        self.test_timeout.setValue(240)
        self.test_timeout.setMaximumWidth(180)
        test_grid.addWidget(self.test_timeout, 0, 3)

        self.btn_run_unittests = QPushButton("Yerel test suite çalıştır", controls)
        self.btn_run_unittests.setMinimumHeight(38)
        self.btn_run_unittests.clicked.connect(self.run_unittest_suite)
        test_grid.addWidget(self.btn_run_unittests, 1, 0, 1, 4)
        controls_lay.addLayout(test_grid)

        divider = QFrame(controls)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("Divider")
        controls_lay.addWidget(divider)

        smoke_header = QHBoxLayout()
        smoke_titles = QVBoxLayout()
        smoke_title = QLabel("Domain smoke testleri")
        smoke_title.setStyleSheet("font-size:16px; font-weight:900; color:#0F172A;")
        smoke_desc = QLabel("Bu bölüm tests klasörünü değil, domain pipeline smoke akışlarını çalıştırır.")
        smoke_desc.setObjectName("Muted")
        smoke_titles.addWidget(smoke_title)
        smoke_titles.addWidget(smoke_desc)
        smoke_header.addLayout(smoke_titles)
        smoke_header.addStretch(1)
        self.btn_run_healthcheck_from_diag = QPushButton("Tüm smoke'ları çalıştır", controls)
        self.btn_run_healthcheck_from_diag.setObjectName("PrimaryBtn")
        self.btn_run_healthcheck_from_diag.setMinimumHeight(38)
        self.btn_run_healthcheck_from_diag.clicked.connect(self.run_healthcheck)
        smoke_header.addWidget(self.btn_run_healthcheck_from_diag)
        controls_lay.addLayout(smoke_header)

        self.btn_run_listing_order_smoke = QPushButton("Listing->Sipariş", controls)
        self.btn_run_listing_order_smoke.setMinimumHeight(38)
        self.btn_run_listing_order_smoke.clicked.connect(self.verify_listing_order_flow)

        self.btn_run_cargo_sandbox = QPushButton("Kargo sandbox", controls)
        self.btn_run_cargo_sandbox.setMinimumHeight(38)
        self.btn_run_cargo_sandbox.clicked.connect(self.run_cargo_sandbox)

        self.btn_run_stock_depletion = QPushButton("Stok tüketimi", controls)
        self.btn_run_stock_depletion.setMinimumHeight(38)
        self.btn_run_stock_depletion.clicked.connect(self.run_stock_depletion)

        self.btn_run_label_stress = QPushButton("Etiket stress", controls)
        self.btn_run_label_stress.setMinimumHeight(38)
        self.btn_run_label_stress.clicked.connect(self.run_label_stress)

        smoke_grid = QGridLayout()
        smoke_grid.setHorizontalSpacing(12)
        smoke_grid.setVerticalSpacing(5)
        smoke_grid.setColumnStretch(1, 1)
        smoke_grid.setColumnStretch(2, 3)
        for col, text in enumerate(("Domain", "Test", "Kapsam")):
            header = QLabel(text)
            header.setObjectName("Muted")
            header.setStyleSheet("font-weight:800; color:#64748B;")
            smoke_grid.addWidget(header, 0, col)

        def add_smoke_row(row: int, domain: str, test: str, scope: str) -> None:
            domain_lbl = QLabel(domain)
            domain_lbl.setStyleSheet("font-weight:900; color:#0F172A;")
            test_lbl = QLabel(test)
            test_lbl.setStyleSheet("font-weight:800; color:#0F172A;")
            scope_lbl = QLabel(scope)
            scope_lbl.setObjectName("Muted")
            scope_lbl.setWordWrap(True)
            smoke_grid.addWidget(domain_lbl, row, 0)
            smoke_grid.addWidget(test_lbl, row, 1)
            smoke_grid.addWidget(scope_lbl, row, 2)

        add_smoke_row(1, "Account", "Şirket context", "Şirket listesi + seçili şirket.")
        add_smoke_row(2, "Listing", "Listing gelişi", "Listing üretimi + DB okuma.")
        add_smoke_row(3, "Orders", "Listing -> Sipariş", "Listing kaynağından sipariş.")
        add_smoke_row(4, "Labels", "Label payload", "Siparişten label payload.")
        add_smoke_row(5, "Stock", "Stok katalog", "Item, depo ve marka okuma.")
        add_smoke_row(6, "Logistics", "Kargo sandbox", "Platform, firma, fiyat, desi.")
        add_smoke_row(7, "Labels", "Etiket stress", "Label export dayanıklılığı.")
        controls_lay.addLayout(smoke_grid)

        smoke_actions = QHBoxLayout()
        smoke_actions.setSpacing(10)
        for btn in (
            self.btn_run_listing_order_smoke,
            self.btn_run_cargo_sandbox,
            self.btn_run_stock_depletion,
            self.btn_run_label_stress,
        ):
            btn.setMinimumHeight(36)
            smoke_actions.addWidget(btn)
        controls_lay.addLayout(smoke_actions)

        params_divider = QFrame(controls)
        params_divider.setFrameShape(QFrame.Shape.HLine)
        params_divider.setObjectName("Divider")
        controls_lay.addWidget(params_divider)

        params_title = QLabel("Sandbox parametreleri")
        params_title.setStyleSheet("font-size:15px; font-weight:900; color:#0F172A;")
        controls_lay.addWidget(params_title)

        params_grid = QGridLayout()
        params_grid.setHorizontalSpacing(12)
        params_grid.setVerticalSpacing(10)
        for col in range(4):
            params_grid.setColumnStretch(col, 1)
        params_grid.setRowMinimumHeight(0, 68)
        params_grid.setRowMinimumHeight(1, 68)
        params_grid.setRowMinimumHeight(2, 46)

        def add_param(row: int, col: int, label: str, widget: QWidget) -> None:
            host = QWidget(controls)
            host.setMinimumHeight(66)
            host_lay = QVBoxLayout(host)
            host_lay.setContentsMargins(0, 0, 0, 0)
            host_lay.setSpacing(4)
            lbl = QLabel(label, host)
            lbl.setObjectName("Muted")
            widget.setMinimumHeight(38)
            host_lay.addWidget(lbl)
            host_lay.addWidget(widget)
            params_grid.addWidget(host, row, col)

        self.cargo_platform_input = QLineEdit(controls)
        self.cargo_platform_input.setText("TRENDYOL")
        add_param(0, 0, "Kargo platform", self.cargo_platform_input)

        self.cargo_provider_input = QLineEdit(controls)
        self.cargo_provider_input.setText("ARASMP")
        add_param(0, 1, "Kargo firma", self.cargo_provider_input)

        self.cargo_sale_price_input = QLineEdit(controls)
        self.cargo_sale_price_input.setText("114.99")
        add_param(0, 2, "Satış fiyatı", self.cargo_sale_price_input)

        self.cargo_desi_input = QLineEdit(controls)
        self.cargo_desi_input.setText("1")
        add_param(0, 3, "Desi", self.cargo_desi_input)

        self.stock_depletion_count = NumberStepper(controls, minimum=1, maximum=1000, step=10)
        self.stock_depletion_count.setValue(250)
        add_param(1, 0, "Stok tüketimi", self.stock_depletion_count)

        self.label_stress_count = NumberStepper(controls, minimum=1, maximum=1000, step=25)
        self.label_stress_count.setValue(250)
        add_param(1, 1, "Etiket stress", self.label_stress_count)

        self.chaos_mode_combo = QComboBox(controls)
        self._populate_combo(
            self.chaos_mode_combo,
            [
                ("off", "Kapalı"),
                ("timeout", "Timeout"),
                ("429", "HTTP 429"),
                ("network", "Network Error"),
            ],
        )
        add_param(1, 2, "Chaos", self.chaos_mode_combo)

        self.chaos_rate_spin = NumberStepper(controls, minimum=0, maximum=100, step=5)
        self.chaos_rate_spin.setValue(30)
        add_param(1, 3, "Chaos %", self.chaos_rate_spin)

        self.btn_apply_chaos = QPushButton("Chaos uygula", controls)
        self.btn_apply_chaos.setMinimumHeight(38)
        self.btn_apply_chaos.clicked.connect(self.apply_chaos_mode)
        params_grid.addWidget(self.btn_apply_chaos, 2, 0, 1, 4)
        controls_lay.addLayout(params_grid)
        controls.setMinimumHeight(controls.sizeHint().height())

        controls_scroll = QScrollArea(page)
        controls_scroll.setObjectName("DiagnosticsControlsScroll")
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        controls_scroll.setWidget(controls)
        controls_scroll.setMinimumHeight(460)

        out_frame = QFrame(page)
        out_frame.setObjectName("Card")
        out_frame.setMinimumHeight(140)
        out_lay = QVBoxLayout(out_frame)
        out_lay.setContentsMargins(10, 10, 10, 10)
        out_lay.setSpacing(6)

        out_top = QHBoxLayout()
        out_top.addWidget(QLabel("Canlı Log"))
        out_top.addStretch(1)
        self.btn_clear_diag_log = QPushButton("Log temizle", out_frame)
        self.btn_clear_diag_log.clicked.connect(lambda: self.diagnostics_output.clear() if self.diagnostics_output is not None else None)
        out_top.addWidget(self.btn_clear_diag_log)
        out_lay.addLayout(out_top)

        self.diagnostics_output = QTextEdit(out_frame)
        self.diagnostics_output.setReadOnly(True)
        self.diagnostics_output.setPlaceholderText("Domain check ve unittest çıktıları burada görünür...")
        self.diagnostics_output.setMinimumHeight(74)
        out_lay.addWidget(self.diagnostics_output)

        self.diagnostics_controls_card = controls
        self.diagnostics_controls_scroll = controls_scroll
        self.diagnostics_log_card = out_frame

        splitter = self._build_resizable_log_splitter(
            page,
            controls_scroll,
            out_frame,
            top_size=max(720, controls.minimumHeight() + 48),
            log_size=160,
        )
        root.addWidget(splitter, 1)

        self._busy_widgets.extend([
            self.btn_run_cargo_sandbox,
            self.btn_run_stock_depletion,
            self.btn_run_label_stress,
            self.btn_run_listing_order_smoke,
            self.btn_apply_chaos,
            self.btn_run_unittests,
            self.btn_run_healthcheck_from_diag,
            self.test_pattern,
            self.btn_clear_diag_log,
        ])

        return page

    def _open_feature_window(
        self,
        *,
        key: str,
        title: str,
        builder: Callable[[QWidget], QWidget],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        wnd = self._feature_windows.get(key)
        if wnd is not None and wnd.isVisible():
            wnd.raise_()
            wnd.activateWindow()
            return

        wnd = QDialog(self)
        wnd.setWindowFlags(
            wnd.windowFlags()
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        wnd.setSizeGripEnabled(True)
        wnd.setWindowTitle(title)
        wnd.setMinimumSize(1100, 760)
        wnd.resize(1280, 860)
        wnd.setStyleSheet(self.styleSheet())
        wnd.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        lay = QVBoxLayout(wnd)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(0)
        lay.addWidget(builder(wnd), 1)

        def _cleanup() -> None:
            self._feature_windows.pop(key, None)
            if on_close:
                on_close()
            self._cleanup_busy_widgets()

        wnd.finished.connect(lambda _r=0: _cleanup())
        self._feature_windows[key] = wnd
        wnd.showMaximized()
        wnd.raise_()
        wnd.activateWindow()

    def _open_order_sim_window(self) -> None:
        def _cleanup() -> None:
            self.quick_order_count = None
            self.quick_lines_per_order = None
            self.quick_lifecycle_preset = None
            self.btn_sim_orders = None
            self.btn_clear_quick_order_log = None
            self.quick_order_log = None
        self._open_feature_window(
            key="order_sim",
            title=TEST_LAB_ORDER_WINDOW_TITLE,
            builder=self._build_order_simulation_page,
            on_close=_cleanup,
        )

    def _open_listing_order_window(self) -> None:
        def _cleanup() -> None:
            self.listing_search = None
            self.listing_company_label = None
            self.listing_stock_filter = None
            self.listing_positive_stock_only = None
            self.btn_listing_filter_clear = None
            self.listing_metric_total = None
            self.listing_metric_selected = None
            self.listing_metric_linked = None
            self.listing_metric_missing = None
            self.listing_cards_scroll = None
            self.listing_cards_host = None
            self.listing_cards_layout = None
            self._listing_row_widgets = []
            self._listing_items_cache = []
            self._listing_total_count = 0
            self.btn_load_listings = None
            self.btn_listing_selection_toggle = None
            self.listing_table = None
            self.listing_order_count = None
            self.listing_lifecycle_preset = None
            self.btn_sim_orders_from_listings = None
            self.btn_verify_listing_order_flow = None
            self.btn_clear_listing_order_log = None
            self.listing_order_log = None
        self._open_feature_window(
            key="listing_order_sim",
            title=TEST_LAB_LISTING_ORDER_WINDOW_TITLE,
            builder=self._build_listing_order_page,
            on_close=_cleanup,
        )
        QTimer.singleShot(30, self.load_listings)

    def _open_listing_sim_window(self) -> None:
        def _cleanup() -> None:
            self.quick_listing_count = None
            self.btn_sim_listings = None
            self.btn_clear_listing_sim_log = None
            self.listing_sim_log = None
        self._open_feature_window(
            key="listing_sim",
            title=TEST_LAB_LISTING_SIM_WINDOW_TITLE,
            builder=self._build_listing_simulation_page,
            on_close=_cleanup,
        )

    def _open_stage_window(self) -> None:
        def _cleanup() -> None:
            self.stage_account_pill = None
            self.stage_listing_combo = None
            self.stage_quantity = None
            self.stage_order_combo = None
            self.stage_status_combo = None
            self.stage_claim_combo = None
            self.btn_stage_create_order = None
            self.btn_stage_advance_order = None
            self.btn_stage_create_return = None
            self.btn_stage_waiting_action = None
            self.btn_stage_approve_return = None
            self.btn_stage_full_lifecycle = None
            self.btn_stage_refresh = None
            self.btn_clear_stage_log = None
            self.stage_log = None

        self._open_feature_window(
            key="stage_lab",
            title=TEST_LAB_STAGE_WINDOW_TITLE,
            builder=self._build_stage_page,
            on_close=_cleanup,
        )
        if self._worker is not None:
            self._pending_stage_load = True
            self._append_stage_log("Stage bağlamı sıraya alındı; şirket yüklemesi bitince başlayacak.")
        else:
            QTimer.singleShot(0, self.load_stage_context)

    def _open_diagnostics_window(self) -> None:
        def _cleanup() -> None:
            self.test_pattern = None
            self.test_timeout = None
            self.cargo_platform_input = None
            self.cargo_provider_input = None
            self.cargo_sale_price_input = None
            self.cargo_desi_input = None
            self.btn_run_cargo_sandbox = None
            self.stock_depletion_count = None
            self.btn_run_stock_depletion = None
            self.label_stress_count = None
            self.btn_run_label_stress = None
            self.chaos_mode_combo = None
            self.chaos_rate_spin = None
            self.btn_apply_chaos = None
            self.btn_run_unittests = None
            self.btn_run_healthcheck_from_diag = None
            self.btn_run_listing_order_smoke = None
            self.btn_clear_diag_log = None
            self.diagnostics_output = None
            self.diagnostics_controls_card = None
            self.diagnostics_controls_scroll = None
            self.diagnostics_log_card = None
        self._open_feature_window(
            key="diagnostics",
            title=TEST_LAB_DIAGNOSTICS_WINDOW_TITLE,
            builder=self._build_diagnostics_page,
            on_close=_cleanup,
        )

    def _set_busy(self, busy: bool) -> None:
        self._cleanup_busy_widgets()
        for w in self._busy_widgets:
            try:
                w.setEnabled(not busy)
            except Exception:
                continue
        self.status_pill.setText(TEST_LAB_STATUS_BUSY_TEXT if busy else TEST_LAB_STATUS_READY_TEXT)

    def _cleanup_busy_widgets(self) -> None:
        alive: list[QWidget] = []
        for w in self._busy_widgets:
            if w is None:
                continue
            try:
                w.objectName()
                alive.append(w)
            except Exception:
                continue
        self._busy_widgets = alive

    def _append_log(self, text: str) -> None:
        line = f"[{_now_str()}] {text}"
        self._global_log_lines.append(line)
        if len(self._global_log_lines) > 500:
            self._global_log_lines = self._global_log_lines[-500:]

    def _append_quick_order_log(self, text: str) -> None:
        line = f"[{_now_str()}] {text}"
        widget = getattr(self, "quick_order_log", None)
        if widget is None:
            return
        try:
            widget.append(line)
        except Exception:
            pass

    def _append_listing_order_log(self, text: str) -> None:
        line = f"[{_now_str()}] {text}"
        widget = getattr(self, "listing_order_log", None)
        if widget is None:
            return
        try:
            widget.append(line)
        except Exception:
            pass

    def _append_listing_sim_log(self, text: str) -> None:
        line = f"[{_now_str()}] {text}"
        widget = getattr(self, "listing_sim_log", None)
        if widget is None:
            return
        try:
            widget.append(line)
        except Exception:
            pass

    def _append_stage_log(self, text: str) -> None:
        line = f"[{_now_str()}] {text}"
        widget = getattr(self, "stage_log", None)
        if widget is None:
            return
        try:
            widget.append(line)
            widget.ensureCursorVisible()
        except Exception:
            pass

    def _append_diag(self, text: str) -> None:
        widget = getattr(self, "diagnostics_output", None)
        if widget is None:
            return
        try:
            widget.append(text)
        except Exception:
            pass

    def _append_release_log(self, text: str) -> None:
        line = f"[{_now_str()}] {text}"
        widget = getattr(self, "release_log_output", None)
        if widget is None:
            return
        try:
            widget.append(line)
            widget.ensureCursorVisible()
        except Exception:
            pass

    def _append_release_log_chunk(self, payload: str) -> None:
        text = str(payload or "")
        if not text:
            return
        for line in text.splitlines():
            clean = str(line or "").strip()
            if not clean:
                continue
            self._append_release_log(clean)

    def start_release_build(self) -> None:
        if self._build_worker is not None:
            return

        version = str(APP_VERSION or "").strip()
        if not version:
            if getattr(self, "btn_build_release", None) is not None:
                self.btn_build_release.fail()
            AppMessageCenter.warning(self, TEST_LAB_BUILD_MESSAGE_TITLE, "APP_VERSION boş olamaz.")
            return

        output_dir = str(Path.home() / "Desktop" / "os-release")

        self.release_stage_label.setText(TEST_LAB_BUILD_STAGE_STARTING_TEXT)
        self.release_output_hint.setText(TEST_LAB_BUILD_OUTPUT_HINT_TEMPLATE.format(path=output_dir))
        self._append_release_log(f"Release başladı | version={version} | output={output_dir}")
        if getattr(self, "btn_build_release", None) is not None:
            self.btn_build_release.setProgress(1)

        worker = _ReleaseBuildWorker(version=version, output_root=output_dir, parent=self)
        self._build_worker = worker
        worker.progress_changed.connect(self._on_release_build_progress)
        worker.log_line.connect(self._append_release_log_chunk)
        worker.result_ready.connect(self._on_release_build_result)
        worker.finished.connect(self._on_release_build_finished)

        self._set_busy(True)
        worker.start()

    def _on_release_build_progress(self, percent: int, stage: str) -> None:
        stage_text = str(stage or "").strip() or "Çalışıyor..."
        self.release_stage_label.setText(f"{stage_text} ({int(percent)}%)")
        if getattr(self, "btn_build_release", None) is not None:
            self.btn_build_release.setProgress(int(percent))

    def _on_release_build_result(self, result: Result) -> None:
        if not isinstance(result, Result):
            result = Result.fail("Release worker beklenmeyen sonuc dondurdu.", close_dialog=False)

        if not result.success:
            self.release_stage_label.setText(TEST_LAB_BUILD_STAGE_FAILED_TEXT)
            self._append_release_log(f"ERROR: {result.message}")
            if getattr(self, "btn_build_release", None) is not None:
                self.btn_build_release.fail()
            AppMessageCenter.error(self, TEST_LAB_BUILD_MESSAGE_TITLE, result.message or "Release işlemi başarısız.")
            return

        data = result.data or {}
        exe_path = str(data.get("exe_path") or "").strip()
        setup_path = str(data.get("setup_path") or "").strip()
        output_root = str(data.get("output_root") or "").strip()
        release_url = str(data.get("release_url") or "").strip()
        asset_url = str(data.get("asset_url") or "").strip()
        setup_sha256 = str(data.get("setup_sha256") or "").strip()
        self._last_release_output_dir = output_root
        self.release_output_hint.setText(TEST_LAB_BUILD_OUTPUT_HINT_TEMPLATE.format(path=output_root))
        self.release_stage_label.setText("Release tamamlandı (100%)")
        self._append_release_log("Release tamamlandı.")
        self._append_release_log(f"EXE: {exe_path}")
        self._append_release_log(f"SETUP: {setup_path}")
        if release_url:
            self._append_release_log(f"RELEASE: {release_url}")
        if asset_url:
            self._append_release_log(f"ASSET: {asset_url}")
        if setup_sha256:
            self._append_release_log(f"SHA256: {setup_sha256}")
        if getattr(self, "btn_build_release", None) is not None:
            self.btn_build_release.setProgress(100)
        if getattr(self, "btn_open_last_release_dir", None) is not None:
            self.btn_open_last_release_dir.setEnabled(bool(output_root))

        AppMessageCenter.info(
            self,
            TEST_LAB_BUILD_SUCCESS_TITLE,
            (
                "Release yayinlandi.\n\n"
                f"SETUP: {setup_path}\n"
                f"GitHub: {release_url or '-'}"
            ),
        )

    def _on_release_build_finished(self) -> None:
        self._build_worker = None
        self._set_busy(False)

    def _open_last_release_output_dir(self) -> None:
        folder = str(self._last_release_output_dir or "").strip()
        if not folder:
            AppMessageCenter.warning(self, TEST_LAB_BUILD_MESSAGE_TITLE, "Açılacak bir çıktı klasörü yok.")
            return
        path = Path(folder)
        if not path.exists():
            AppMessageCenter.warning(self, TEST_LAB_BUILD_MESSAGE_TITLE, f"Klasör bulunamadı:\n{folder}")
            return
        try:
            if os.name == "nt":
                os.startfile(str(path))
                return
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)], close_fds=True)
                return
            subprocess.Popen(["xdg-open", str(path)], close_fds=True)
        except Exception as e:
            AppMessageCenter.error(self, "Build", str(e))

    def _selected_company_pk(self) -> int | None:
        data = self.company_combo.currentData()
        try:
            return int(data) if data is not None else None
        except Exception:
            return None

    def _run_worker(
        self,
        func: Callable,
        *,
        done: Callable[[Result], None],
        **kwargs,
    ) -> None:
        if self._worker is not None:
            if func is action_load_company_listings:
                self._pending_listing_load = True
                self._append_listing_order_log("Listing yükleme sıraya alındı; mevcut işlem bitince tekrar denenecek.")
            elif func is action_load_stage_lab_context:
                self._pending_stage_load = True
                self._append_stage_log("Stage bağlamı sıraya alındı; mevcut işlem bitince tekrar denenecek.")
            return

        self._set_busy(True)
        self._worker = SyncWorker(func, parent=self, **kwargs)
        self._worker.result_ready.connect(done)

        def _finish() -> None:
            self._set_busy(False)
            self._worker = None
            if self._pending_listing_load:
                self._pending_listing_load = False
                if (
                    (
                        getattr(self, "listing_table", None) is not None
                        or getattr(self, "listing_cards_layout", None) is not None
                    )
                    and getattr(self, "listing_search", None) is not None
                ):
                    QTimer.singleShot(0, self.load_listings)
            if self._pending_stage_load:
                self._pending_stage_load = False
                if getattr(self, "stage_listing_combo", None) is not None:
                    QTimer.singleShot(0, self.load_stage_context)

        self._worker.finished.connect(_finish)
        self._worker.start()

    def _on_company_changed(self) -> None:
        idx = self.company_combo.currentIndex()
        if idx < 0 or idx >= len(self._companies):
            self.company_info.setText("Seçim yok")
            return

        c = self._companies[idx]
        company_pk = int(c.get("pk"))
        self.company_info.setText(
            f"{c.get('platform', '-')} | account={c.get('account_id', '-')} | active={c.get('is_active', False)}"
        )
        self._update_listing_company_label()
        if (
            self._worker is None
            and self._last_listing_company_pk != company_pk
            and (
                getattr(self, "listing_table", None) is not None
                or getattr(self, "listing_cards_layout", None) is not None
            )
            and getattr(self, "listing_search", None) is not None
        ):
            self.load_listings()
        if self._worker is None and getattr(self, "stage_listing_combo", None) is not None:
            QTimer.singleShot(0, self.load_stage_context)

    def load_companies(self) -> None:
        self._append_log("Şirket listesi yükleniyor...")

        def _done(res: Result) -> None:
            if not res.success:
                self._append_log(f"ERROR: {res.message}")
                AppMessageCenter.error(self, "Test Lab", res.message or "Şirketler yüklenemedi.")
                return

            self._companies = (res.data or {}).get("companies", []) or []
            with QSignalBlocker(self.company_combo):
                self.company_combo.clear()

                for c in self._companies:
                    label = (
                        f"{c.get('comp_name', '-')}"
                        f" | {c.get('platform', '-')}"
                        f" | {c.get('account_id', '-')}"
                    )
                    self.company_combo.addItem(label, c.get("pk"))
            self._on_company_changed()
            self._append_log(f"OK: {len(self._companies)} şirket yüklendi.")

        self._run_worker(action_load_test_companies, done=_done)

    def load_listings(self) -> None:
        if (
            getattr(self, "listing_table", None) is None
            and getattr(self, "listing_cards_layout", None) is None
        ) or getattr(self, "listing_search", None) is None:
            return
        if self._worker is not None:
            self._pending_listing_load = True
            self._append_listing_order_log("Listing yükleme sıraya alındı; mevcut işlem bitince tekrar denenecek.")
            return
        company_pk = self._selected_company_pk()
        if company_pk is None:
            AppMessageCenter.warning(self, "Test Lab", "Önce bir şirket seç.")
            return

        search = (self.listing_search.text() or "").strip()
        self._append_log(f"Listingler yükleniyor (company={company_pk}, search='{search}')...")
        self._append_listing_order_log(f"Listingler yükleniyor (company={company_pk}, search='{search}')...")

        def _done(res: Result) -> None:
            if not res.success:
                self._append_log(f"ERROR: {res.message}")
                self._append_listing_order_log(f"ERROR: {res.message}")
                AppMessageCenter.error(self, "Test Lab", res.message or "Listingler yüklenemedi.")
                return

            items = (res.data or {}).get("items", []) or []
            total = int((res.data or {}).get("total", len(items)) or len(items))
            self._populate_listing_table(items)
            self._listing_items_cache = list(items)
            self._listing_total_count = total
            self._apply_listing_order_filters()
            self._last_listing_company_pk = company_pk
            self._append_log(f"OK: listing loaded (shown={len(items)}, total={total}).")
            self._append_listing_order_log(f"OK: listing loaded (shown={len(items)}, total={total}).")

        self._run_worker(
            action_load_company_listings,
            done=_done,
            api_account_id=company_pk,
            search=search,
            limit=500,
        )

    @staticmethod
    def _combo_text_data(combo: QComboBox | None) -> str:
        if combo is None:
            return ""
        data = combo.currentData()
        if isinstance(data, dict):
            return str(
                data.get("order_number")
                or data.get("claim_id")
                or data.get("barcode")
                or ""
            ).strip()
        return str(data or "").strip()

    @staticmethod
    def _restore_combo_data(combo: QComboBox, identity: str) -> None:
        needle = str(identity or "").strip()
        if not needle:
            return
        for index in range(combo.count()):
            data = combo.itemData(index)
            if isinstance(data, dict):
                value = str(
                    data.get("order_number")
                    or data.get("claim_id")
                    or data.get("barcode")
                    or ""
                ).strip()
            else:
                value = str(data or "").strip()
            if value == needle:
                combo.setCurrentIndex(index)
                return

    def load_stage_context(self) -> None:
        if getattr(self, "stage_listing_combo", None) is None:
            return
        company_pk = self._selected_company_pk()
        if company_pk is None:
            AppMessageCenter.warning(self, "Test Lab", "Önce bir şirket seç.")
            return

        previous_listing = self._combo_text_data(self.stage_listing_combo)
        previous_order = self._combo_text_data(self.stage_order_combo)
        previous_claim = self._combo_text_data(self.stage_claim_combo)
        self._append_stage_log(f"Stage bağlamı yükleniyor (company={company_pk})...")

        def _done(res: Result) -> None:
            if not res.success:
                if getattr(self, "stage_account_pill", None) is not None:
                    self.stage_account_pill.setText("Stage güvenlik kontrolü başarısız")
                self._append_stage_log(f"FAIL: {res.message}")
                AppMessageCenter.warning(self, "Test Lab", res.message or "Stage bağlamı yüklenemedi.")
                return

            data = res.data or {}
            account = dict(data.get("account") or {})
            self.stage_account_pill.setText(
                f"STAGE • {account.get('company_name') or '-'} • seller {account.get('seller_id') or '-'}"
            )

            with QSignalBlocker(self.stage_listing_combo):
                self.stage_listing_combo.clear()
                for item in list(data.get("listings") or []):
                    if item.get("official_test_product"):
                        label = (
                            f"ÖNERİLEN • {item.get('title')} | "
                            f"barkod={item.get('barcode')}"
                        )
                    else:
                        label = (
                            f"{item.get('title') or item.get('barcode')} | "
                            f"barkod={item.get('barcode')} | stok={item.get('quantity', '-')}"
                        )
                    self.stage_listing_combo.addItem(label, item)
                self._restore_combo_data(self.stage_listing_combo, previous_listing)

            with QSignalBlocker(self.stage_order_combo):
                self.stage_order_combo.clear()
                for item in list(data.get("orders") or []):
                    label = (
                        f"{item.get('order_number')} | {item.get('status') or '-'} | "
                        f"paket={item.get('shipment_package_id') or '-'}"
                    )
                    self.stage_order_combo.addItem(label, item)
                self._restore_combo_data(self.stage_order_combo, previous_order)

            with QSignalBlocker(self.stage_claim_combo):
                self.stage_claim_combo.clear()
                for item in list(data.get("claims") or []):
                    label = (
                        f"{item.get('claim_id')} | {item.get('status') or '-'} | "
                        f"sipariş={item.get('order_number') or '-'}"
                    )
                    self.stage_claim_combo.addItem(label, item)
                self._restore_combo_data(self.stage_claim_combo, previous_claim)

            self._append_stage_log(
                "OK: Stage bağlamı hazır "
                f"(ilan={self.stage_listing_combo.count()}, sipariş={self.stage_order_combo.count()}, "
                f"iade={self.stage_claim_combo.count()})."
            )

        self._run_worker(action_load_stage_lab_context, done=_done, api_account_id=company_pk)

    def _selected_stage_listing(self) -> dict:
        data = self.stage_listing_combo.currentData() if self.stage_listing_combo is not None else None
        return dict(data) if isinstance(data, dict) else {}

    def _selected_stage_order(self) -> dict:
        data = self.stage_order_combo.currentData() if self.stage_order_combo is not None else None
        return dict(data) if isinstance(data, dict) else {}

    def _selected_stage_claim(self) -> dict:
        data = self.stage_claim_combo.currentData() if self.stage_claim_combo is not None else None
        return dict(data) if isinstance(data, dict) else {}

    def _stage_operation_finished(self, result: Result, *, success_prefix: str) -> None:
        if not result.success:
            self._append_stage_log(f"FAIL: {result.message}")
            AppMessageCenter.warning(self, "Test Lab", result.message or "Stage işlemi başarısız.")
            return
        self._append_stage_log(f"OK: {success_prefix}: {result.message}")
        data = result.data or {}
        if data.get("order_number"):
            self._append_stage_log(
                f"kanıt: order={data.get('order_number')} status={data.get('status') or '-'}"
            )
        if data.get("claim_id"):
            self._append_stage_log(
                f"kanıt: claim={data.get('claim_id')} status={data.get('status') or '-'}"
            )
        QTimer.singleShot(80, self.load_stage_context)

    def create_stage_order(self) -> None:
        company_pk = self._selected_company_pk()
        listing = self._selected_stage_listing()
        if company_pk is None or not listing.get("barcode"):
            AppMessageCenter.warning(self, "Test Lab", "Stage hesabı ve onaylı bir ilan seçmelisin.")
            return
        quantity = int(self.stage_quantity.value())
        self._append_stage_log(
            f"Stage test siparişi oluşturuluyor (barcode={listing.get('barcode')}, qty={quantity})..."
        )
        self._run_worker(
            action_create_stage_test_order,
            done=lambda res: self._stage_operation_finished(res, success_prefix="sipariş oluşturma"),
            api_account_id=company_pk,
            barcode=str(listing.get("barcode") or ""),
            quantity=quantity,
        )

    def advance_stage_order(self) -> None:
        company_pk = self._selected_company_pk()
        order = self._selected_stage_order()
        order_number = str(order.get("order_number") or "").strip()
        target_status = str(self.stage_status_combo.currentData() or "").strip()
        if company_pk is None or not order_number or not target_status:
            AppMessageCenter.warning(self, "Test Lab", "Stage siparişi ve hedef durum seçmelisin.")
            return
        self._append_stage_log(f"Sipariş ilerletiliyor (order={order_number}, target={target_status})...")
        self._run_worker(
            action_advance_stage_order_status,
            done=lambda res: self._stage_operation_finished(res, success_prefix="sipariş durumu"),
            api_account_id=company_pk,
            order_number=order_number,
            target_status=target_status,
        )

    def create_stage_return(self) -> None:
        company_pk = self._selected_company_pk()
        order = self._selected_stage_order()
        order_number = str(order.get("order_number") or "").strip()
        if company_pk is None or not order_number:
            AppMessageCenter.warning(self, "Test Lab", "İade oluşturulacak Stage siparişini seçmelisin.")
            return
        quantity = int(self.stage_quantity.value())
        self._append_stage_log(f"Stage iadesi oluşturuluyor (order={order_number}, qty={quantity})...")
        self._run_worker(
            action_create_stage_return_claim,
            done=lambda res: self._stage_operation_finished(res, success_prefix="iade oluşturma"),
            api_account_id=company_pk,
            order_number=order_number,
            quantity=quantity,
        )

    def advance_stage_claim(self) -> None:
        company_pk = self._selected_company_pk()
        claim = self._selected_stage_claim()
        claim_id = str(claim.get("claim_id") or "").strip()
        if company_pk is None or not claim_id:
            AppMessageCenter.warning(self, "Test Lab", "WaitingInAction yapılacak iadeyi seçmelisin.")
            return
        self._append_stage_log(f"İade WaitingInAction yapılıyor (claim={claim_id})...")
        self._run_worker(
            action_advance_stage_claim_to_waiting_action,
            done=lambda res: self._stage_operation_finished(res, success_prefix="iade durum ilerletme"),
            api_account_id=company_pk,
            claim_id=claim_id,
        )

    def approve_stage_return(self) -> None:
        company_pk = self._selected_company_pk()
        claim = self._selected_stage_claim()
        claim_id = str(claim.get("claim_id") or "").strip()
        if company_pk is None or not claim_id:
            AppMessageCenter.warning(self, "Test Lab", "Onaylanacak Stage iadesini seçmelisin.")
            return
        self._append_stage_log(
            f"Uygulamanın gerçek iade onay aksiyonu çalıştırılıyor (claim={claim_id})..."
        )
        self._run_worker(
            action_approve_stage_return,
            done=lambda res: self._stage_operation_finished(res, success_prefix="uygulama iade onayı"),
            api_account_id=company_pk,
            claim_id=claim_id,
        )

    def run_stage_return_lifecycle(self) -> None:
        company_pk = self._selected_company_pk()
        listing = self._selected_stage_listing()
        barcode = str(listing.get("barcode") or "").strip()
        if company_pk is None or not barcode:
            AppMessageCenter.warning(self, "Test Lab", "Stage hesabı ve onaylı bir ilan seçmelisin.")
            return
        quantity = int(self.stage_quantity.value())
        self._append_stage_log(
            "Tam yaşam döngüsü başladı: sipariş oluştur → Shipped → AtCollectionPoint → "
            "Delivered → iade oluştur → WaitingInAction → uygulama aksiyonuyla onayla."
        )

        def _done(res: Result) -> None:
            for step in list((res.data or {}).get("steps") or []):
                icon = "OK" if step.get("success") else "FAIL"
                self._append_stage_log(
                    f"[{icon}] {step.get('step')}: {step.get('detail') or '-'}"
                )
            self._stage_operation_finished(res, success_prefix="tam yaşam döngüsü")

        self._run_worker(
            action_run_stage_return_lifecycle,
            done=_done,
            api_account_id=company_pk,
            barcode=barcode,
            quantity=quantity,
        )

    def _populate_listing_table(self, items: list[dict]) -> None:
        if getattr(self, "listing_table", None) is None:
            return
        table = self.listing_table
        with optimized_table_updates(table, len(items)):
            for row, it in enumerate(items):
                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                check_item.setCheckState(Qt.CheckState.Unchecked)
                check_item.setData(Qt.ItemDataRole.UserRole, it)
                table.setItem(row, 0, check_item)

                table.setItem(row, 1, QTableWidgetItem(str(it.get("product_id") or "")))
                table.setItem(row, 2, QTableWidgetItem(str(it.get("stock_code") or "")))
                table.setItem(row, 3, QTableWidgetItem(str(it.get("title") or "")))
                table.setItem(row, 4, QTableWidgetItem(str(it.get("barcode") or "")))
                table.setItem(row, 5, QTableWidgetItem(str(it.get("quantity") or "")))
                table.setItem(row, 6, QTableWidgetItem(str(it.get("brand") or "")))
        self._sync_listing_selection_toggle_button()

    def _selected_listing_sources(self) -> list[dict]:
        selected: list[dict] = []
        if self._listing_row_widgets:
            for row in self._listing_row_widgets:
                checkbox = row.get("checkbox")
                if checkbox is not None and checkbox.isChecked() and isinstance(row.get("item"), dict):
                    selected.append(row["item"])
            if selected:
                return selected
        if getattr(self, "listing_table", None) is None:
            return selected
        for row in range(self.listing_table.rowCount()):
            chk = self.listing_table.item(row, 0)
            if chk is None:
                continue
            if chk.checkState() != Qt.CheckState.Checked:
                continue
            src = chk.data(Qt.ItemDataRole.UserRole)
            if isinstance(src, dict):
                selected.append(src)
        if selected:
            return selected

        selected_rows = sorted({idx.row() for idx in self.listing_table.selectedIndexes()})
        current_row = int(self.listing_table.currentRow())
        if current_row >= 0:
            selected_rows = sorted(set(selected_rows) | {current_row})
        for row in selected_rows:
            chk = self.listing_table.item(row, 0)
            if chk is None:
                continue
            src = chk.data(Qt.ItemDataRole.UserRole)
            if isinstance(src, dict):
                selected.append(src)
        return selected

    def _visible_listing_sources(self) -> list[dict]:
        items: list[dict] = []
        if self._listing_row_widgets:
            return [row["item"] for row in self._listing_row_widgets if isinstance(row.get("item"), dict)]
        if getattr(self, "listing_table", None) is None:
            return items
        for row in range(self.listing_table.rowCount()):
            chk = self.listing_table.item(row, 0)
            if chk is None:
                continue
            src = chk.data(Qt.ItemDataRole.UserRole)
            if isinstance(src, dict):
                items.append(src)
        return items

    def _mark_listing_row_checked(self, row: int) -> None:
        if getattr(self, "listing_table", None) is None:
            return
        if row < 0 or row >= self.listing_table.rowCount():
            return
        chk = self.listing_table.item(row, 0)
        if chk is None:
            return
        chk.setCheckState(Qt.CheckState.Checked)
        self._sync_listing_selection_toggle_button()

    def _on_listing_table_cell_clicked(self, row: int, column: int) -> None:
        if int(column) == 0:
            self._mark_listing_row_checked(int(row))
            return
        self._sync_listing_selection_toggle_button()

    def select_all_listings(self) -> None:
        if self._listing_row_widgets:
            for row in self._listing_row_widgets:
                checkbox = row.get("checkbox")
                if checkbox is not None:
                    checkbox.setChecked(True)
            self._sync_listing_selection_toggle_button()
            return
        if getattr(self, "listing_table", None) is None:
            return
        with QSignalBlocker(self.listing_table):
            for row in range(self.listing_table.rowCount()):
                chk = self.listing_table.item(row, 0)
                if chk is not None:
                    chk.setCheckState(Qt.CheckState.Checked)
        self._sync_listing_selection_toggle_button()

    def clear_listing_selection(self) -> None:
        if self._listing_row_widgets:
            for row in self._listing_row_widgets:
                checkbox = row.get("checkbox")
                if checkbox is not None:
                    checkbox.setChecked(False)
            self._sync_listing_selection_toggle_button()
            return
        if getattr(self, "listing_table", None) is None:
            return
        with QSignalBlocker(self.listing_table):
            for row in range(self.listing_table.rowCount()):
                chk = self.listing_table.item(row, 0)
                if chk is not None:
                    chk.setCheckState(Qt.CheckState.Unchecked)
        self._sync_listing_selection_toggle_button()

    def _count_selected_listings(self) -> tuple[int, int]:
        if self._listing_row_widgets:
            total = len(self._listing_row_widgets)
            selected = sum(1 for row in self._listing_row_widgets if row.get("checkbox") is not None and row["checkbox"].isChecked())
            return selected, total
        if getattr(self, "listing_table", None) is None:
            return 0, 0
        total = int(self.listing_table.rowCount())
        selected = 0
        for row in range(total):
            chk = self.listing_table.item(row, 0)
            if chk is None:
                continue
            if chk.checkState() == Qt.CheckState.Checked:
                selected += 1
        return selected, total

    def _sync_listing_selection_toggle_button(self) -> None:
        btn = getattr(self, "btn_listing_selection_toggle", None)
        selected, total = self._count_selected_listings()
        metric_total = int(self._listing_total_count or len(self._listing_items_cache))
        self._set_metric_value(getattr(self, "listing_metric_total", None), metric_total)
        self._set_metric_value(getattr(self, "listing_metric_selected", None), selected)
        linked = sum(1 for item in self._listing_items_cache if self._listing_has_stock_link(item))
        self._set_metric_value(getattr(self, "listing_metric_linked", None), linked)
        self._set_metric_value(getattr(self, "listing_metric_missing", None), max(0, len(self._listing_items_cache) - linked))
        if btn is None:
            return
        try:
            btn.setSelectionCounts(selected, total)
        except Exception:
            pass

    def _on_listing_selection_toggle_action(self, action: str) -> None:
        mode = str(action or "").strip().lower()
        if mode == "clear":
            self.clear_listing_selection()
            return
        self.select_all_listings()

    def _on_listing_table_item_changed(self, item: QTableWidgetItem) -> None:
        if item is None:
            return
        if int(item.column()) != 0:
            return
        self._sync_listing_selection_toggle_button()

    def simulate_orders(self) -> None:
        company_pk = self._selected_company_pk()
        if company_pk is None:
            AppMessageCenter.warning(self, "Test Lab", "Önce bir şirket seç.")
            return

        order_count = self.quick_order_count.value()
        lines_per_order = self.quick_lines_per_order.value()
        lifecycle_key = str(self.quick_lifecycle_preset.currentData() or "created")
        self._append_log(
            "Sipariş simülasyonu başladı "
            f"(company={company_pk}, orders={order_count}, lines={lines_per_order}, "
            f"lifecycle={lifecycle_key})..."
        )
        self._append_quick_order_log(
            "Sipariş simülasyonu başladı "
            f"(company={company_pk}, orders={order_count}, lines={lines_per_order}, "
            f"lifecycle={lifecycle_key})..."
        )

        def _done(res: Result) -> None:
            if not res.success:
                self._append_log(f"ERROR: {res.message}")
                self._append_quick_order_log(f"ERROR: {res.message}")
                AppMessageCenter.error(self, "Test Lab", res.message or "Sipariş simülasyonu başarısız.")
                return

            order_numbers = (res.data or {}).get("order_numbers", []) or []
            snapshot_count = int((res.data or {}).get("snapshot_count", 0) or 0)
            self._append_log(f"OK: {len(order_numbers)} sipariş simüle edildi (snapshots={snapshot_count}).")
            self._append_quick_order_log(f"OK: {len(order_numbers)} sipariş simüle edildi (snapshots={snapshot_count}).")

        self._run_worker(
            action_simulate_orders,
            done=_done,
            api_account_id=company_pk,
            order_count=order_count,
            lines_per_order=lines_per_order,
            lifecycle_key=lifecycle_key,
        )

    def simulate_listings(self) -> None:
        company_pk = self._selected_company_pk()
        if company_pk is None:
            AppMessageCenter.warning(self, "Test Lab", "Önce bir şirket seç.")
            return

        count = self.quick_listing_count.value()
        self._append_log(f"Listing simülasyonu başladı (company={company_pk}, items={count})...")
        self._append_listing_sim_log(f"Listing simülasyonu başladı (company={company_pk}, items={count})...")

        def _done(res: Result) -> None:
            if not res.success:
                self._append_log(f"ERROR: {res.message}")
                self._append_listing_sim_log(f"ERROR: {res.message}")
                AppMessageCenter.error(self, "Test Lab", res.message or "Listing simülasyonu başarısız.")
                return

            save = (res.data or {}).get("save", {}) or {}
            counts = save.get("counts", {}) or {}
            self._append_log(
                "OK: listing simülasyonu tamamlandı "
                f"(inserted={counts.get('inserted', 0)}, updated={counts.get('updated', 0)}, history={counts.get('history', 0)})."
            )
            self._append_listing_sim_log(
                "OK: listing simülasyonu tamamlandı "
                f"(inserted={counts.get('inserted', 0)}, updated={counts.get('updated', 0)}, history={counts.get('history', 0)})."
            )
            self._last_listing_company_pk = None
            QTimer.singleShot(60, self.load_listings)

        self._run_worker(
            action_simulate_listings,
            done=_done,
            api_account_id=company_pk,
            item_count=count,
        )

    def simulate_orders_from_listings(self) -> None:
        company_pk = self._selected_company_pk()
        if company_pk is None:
            AppMessageCenter.warning(self, "Test Lab", "Önce bir şirket seç.")
            return

        selected = self._selected_listing_sources()
        if not selected:
            AppMessageCenter.warning(self, "Test Lab", "En az bir listing seçmelisin.")
            return

        order_count = self.listing_order_count.value()
        lifecycle_key = str(self.listing_lifecycle_preset.currentData() or "single")

        self._append_log(
            "Listing tabanlı sipariş simülasyonu başladı "
            f"(sources={len(selected)}, orders={order_count}, lifecycle={lifecycle_key})..."
        )
        self._append_listing_order_log(
            "Listing tabanlı sipariş simülasyonu başladı "
            f"(sources={len(selected)}, orders={order_count}, lifecycle={lifecycle_key})..."
        )

        def _done(res: Result) -> None:
            if not res.success:
                self._append_log(f"ERROR: {res.message}")
                self._append_listing_order_log(f"ERROR: {res.message}")
                AppMessageCenter.error(self, "Test Lab", res.message or "Listing tabanlı sipariş simülasyonu başarısız.")
                return

            order_numbers = (res.data or {}).get("order_numbers", []) or []
            source_count = int((res.data or {}).get("source_count", 0) or 0)
            snapshot_count = int((res.data or {}).get("snapshot_count", 0) or 0)
            self._append_log(
                "OK: listing tabanlı simülasyon tamam "
                f"(orders={len(order_numbers)}, sources={source_count}, snapshots={snapshot_count})."
            )
            self._append_listing_order_log(
                "OK: listing tabanlı simülasyon tamam "
                f"(orders={len(order_numbers)}, sources={source_count}, snapshots={snapshot_count})."
            )

        self._run_worker(
            action_simulate_orders_from_listings,
            done=_done,
            api_account_id=company_pk,
            listing_items=selected,
            order_count=order_count,
            lifecycle_key=lifecycle_key,
        )

    def verify_listing_order_flow(self) -> None:
        company_pk = self._selected_company_pk()
        if company_pk is None:
            AppMessageCenter.warning(self, "Test Lab", "Önce bir şirket seç.")
            return

        selected = self._selected_listing_sources()
        if not selected:
            selected = self._visible_listing_sources()[:3]
        order_count = 1
        lifecycle_key = "created"
        if getattr(self, "listing_order_count", None) is not None:
            order_count = max(1, min(int(self.listing_order_count.value()), 10))
        if getattr(self, "listing_lifecycle_preset", None) is not None:
            lifecycle_key = str(self.listing_lifecycle_preset.currentData() or "created")

        self._append_log(
            "Listing -> sipariş smoke başladı "
            f"(company={company_pk}, sources={len(selected)}, orders={order_count}, lifecycle={lifecycle_key})..."
        )
        self._append_listing_order_log(
            "Smoke doğrulama başladı "
            f"(sources={len(selected)}, orders={order_count}, lifecycle={lifecycle_key})..."
        )
        self._append_diag(
            f"Listing -> sipariş smoke başladı (company={company_pk}, sources={len(selected)}, orders={order_count})."
        )

        def _done(res: Result) -> None:
            if not res.success:
                self._append_log(f"ERROR: {res.message}")
                self._append_listing_order_log(f"ERROR: {res.message}")
                self._append_diag(f"[FAIL] listing.order_smoke: {res.message}")
                AppMessageCenter.error(self, "Test Lab", res.message or "Listing -> sipariş smoke başarısız.")
                return

            data = res.data or {}
            order_numbers = data.get("order_numbers", []) or []
            self._append_log(
                "OK: listing -> sipariş smoke doğrulandı "
                f"(orders={len(order_numbers)}, items={data.get('item_count', 0)}, matched={data.get('matched_item_count', 0)})."
            )
            self._append_listing_order_log(
                "OK: smoke doğrulandı "
                f"(orders={len(order_numbers)}, items={data.get('item_count', 0)}, matched={data.get('matched_item_count', 0)})."
            )
            self._append_diag(
                "[OK] listing.order_smoke: "
                f"orders={len(order_numbers)} items={data.get('item_count', 0)} matched={data.get('matched_item_count', 0)}"
            )

        self._run_worker(
            action_verify_listing_order_flow,
            done=_done,
            api_account_id=company_pk,
            listing_items=selected,
            order_count=order_count,
            lifecycle_key=lifecycle_key,
        )

    def run_healthcheck(self) -> None:
        company_pk = self._selected_company_pk()
        self._append_log("Domain healthcheck başladı...")

        def _done(res: Result) -> None:
            steps = (res.data or {}).get("steps", []) or []
            for st in steps:
                icon = "OK" if st.get("success") else "FAIL"
                self._append_diag(f"[{icon}] {st.get('step')}: {st.get('detail')}")

            if not res.success:
                self._append_log(f"ERROR: {res.message}")
                AppMessageCenter.error(self, "Test Lab", res.message or "Healthcheck başarısız.")
                return

            self._append_log("OK: domain healthcheck tamamlandı.")
            self._append_diag("Healthcheck completed successfully.")

        self._run_worker(
            action_run_domain_healthcheck,
            done=_done,
            api_account_id=company_pk,
        )

    def run_unittest_suite(self) -> None:
        pattern = (self.test_pattern.text() or "test_*.py").strip() or "test_*.py"
        timeout_sec = self.test_timeout.value()
        self._append_log(f"Local unittest suite başladı (pattern={pattern}, timeout={timeout_sec})...")

        def _done(res: Result) -> None:
            data = res.data or {}
            output = (data.get("output") or "").strip()

            if output:
                self._append_diag(output)

            if not res.success:
                self._append_log(f"ERROR: {res.message}")
                AppMessageCenter.warning(self, "Test Lab", res.message or "Unit test suite failed.")
                return

            self._append_log("OK: local unittest suite passed.")

        self._run_worker(
            action_run_local_unittest_suite,
            done=_done,
            pattern=pattern,
            timeout_sec=timeout_sec,
        )

    def run_cargo_sandbox(self) -> None:
        platform_code = str(self.cargo_platform_input.text() or "").strip() or "TRENDYOL"
        provider_code = str(self.cargo_provider_input.text() or "").strip().upper()
        try:
            sale_price = float(str(self.cargo_sale_price_input.text() or "0").replace(",", "."))
            desi = float(str(self.cargo_desi_input.text() or "0").replace(",", "."))
        except Exception:
            AppMessageCenter.warning(self, "Test Lab", "Kargo sandbox için fiyat ve desi sayısal olmalı.")
            return

        self._append_log(
            f"Kargo sandbox başladı (platform={platform_code}, provider={provider_code}, sale_price={sale_price}, desi={desi})..."
        )

        def _done(res: Result) -> None:
            if not res.success:
                self._append_diag(f"[FAIL] cargo.sandbox: {res.message}")
                AppMessageCenter.warning(self, "Test Lab", res.message or "Kargo sandbox başarısız.")
                return
            data = res.data or {}
            self._append_diag(
                "[OK] cargo.sandbox: "
                f"tariff={data.get('matched_tariff_label') or data.get('tariff_label') or '-'} | "
                f"amount={data.get('amount') or data.get('effectiveAmount') or '-'}"
            )

        self._run_worker(
            action_run_cargo_tariff_sandbox,
            done=_done,
            platform_code=platform_code,
            sale_price=sale_price,
            dimensional_weight=desi,
            cargo_provider_code=provider_code,
        )

    def run_stock_depletion(self) -> None:
        item_limit = self.stock_depletion_count.value()
        self._append_log(f"Stok depletion başladı (limit={item_limit})...")

        def _done(res: Result) -> None:
            if not res.success:
                self._append_diag(f"[FAIL] stock.depletion: {res.message}")
                AppMessageCenter.warning(self, "Test Lab", res.message or "Stok depletion başarısız.")
                return
            data = res.data or {}
            self._append_diag(
                f"[OK] stock.depletion: processed={data.get('processed', 0)} depleted={data.get('depleted', 0)}"
            )

        self._run_worker(action_simulate_stock_depletion, done=_done, item_limit=item_limit)

    def run_label_stress(self) -> None:
        company_pk = self._selected_company_pk()
        if company_pk is None:
            AppMessageCenter.warning(self, "Test Lab", "Önce bir şirket seç.")
            return
        order_count = self.label_stress_count.value()
        self._append_log(f"Etiket stres testi başladı (company={company_pk}, orders={order_count})...")

        def _done(res: Result) -> None:
            if not res.success:
                self._append_diag(f"[FAIL] labels.stress: {res.message}")
                AppMessageCenter.warning(self, "Test Lab", res.message or "Etiket stres testi başarısız.")
                return
            data = res.data or {}
            self._append_diag(
                f"[OK] labels.stress: orders={data.get('order_count', 0)} snapshots={data.get('snapshot_count', 0)}"
            )

        self._run_worker(
            action_run_label_stress_test,
            done=_done,
            api_account_id=company_pk,
            order_count=order_count,
        )

    def apply_chaos_mode(self) -> None:
        mode = str(self.chaos_mode_combo.currentData() or "off")
        enabled = mode != "off"
        rate = float(self.chaos_rate_spin.value()) / 100.0
        self._append_log(f"Chaos modu güncelleniyor (enabled={enabled}, mode={mode}, rate={rate:.2f})...")

        def _done(res: Result) -> None:
            if not res.success:
                self._append_diag(f"[FAIL] chaos.mode: {res.message}")
                AppMessageCenter.warning(self, "Test Lab", res.message or "Chaos modu uygulanamadı.")
                return
            state = dict((res.data or {}).get("state") or {})
            self._append_diag(
                f"[OK] chaos.mode: enabled={state.get('enabled')} mode={state.get('mode')} rate={state.get('rate')}"
            )

        self._run_worker(
            action_configure_test_chaos,
            done=_done,
            enabled=enabled,
            mode=mode,
            rate=rate,
        )


