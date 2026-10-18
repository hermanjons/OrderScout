from __future__ import annotations

import json
import os
import tempfile
from typing import TYPE_CHECKING, Any, Optional

from PyQt6.QtCore import Qt, QSignalBlocker, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from Account.signals.signals import account_signals
from Account.views.company_list_widget import CompanyListWidget
from Core.process.process_runner import GenericProcessRunner, ProcessTarget
from Core.threads.async_worker import AsyncWorker
from Core.threads.sync_worker import SyncWorker
from Core.views import (
    ActionPulseButton,
    BadgeButton,
    CircularProgressButton,
    NumberStepper,
    ResettableSplitter,
    SwitchButton,
)
from Core.views.tab_widgets import DashboardHeroCard, QuickAccessSection, SplitPanelSidebar
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from Listing.constants import (
    LISTING_DEFAULT_FETCH_PAGE_SIZE,
    LISTING_STAGE_FETCH_PAGE_SIZE,
    ui_text,
)
from Listing.constants.platform_constants import canonical_platform_code, platform_label_for_code
from Listing.constants.ui_constants import (
    LISTING_AUTO_FETCH_ACTIVE_TEMPLATE,
    LISTING_AUTO_FETCH_LABEL,
    LISTING_AUTO_FETCH_STOPPED_TEXT,
    LISTING_AUTO_FETCH_UNIT_TEXT,
    LISTING_BADGE_BUTTON_TEXT,
    LISTING_FETCH_BUTTON_TEXT,
    LISTING_FETCH_PANEL_TITLE,
    LISTING_QUICK_ACCESS_SUBTITLE,
    LISTING_QUICK_ACCESS_TITLE,
    LISTING_STATUS_FETCHING_COUNT_TEMPLATE,
    LISTING_STATUS_FETCHING_TEXT,
    LISTING_STATUS_IDLE_TEXT,
    LISTING_STATUS_NO_CHANGES_TEXT,
    LISTING_STATUS_PRODUCTS_EMPTY_TEXT,
    LISTING_STATUS_PRODUCTS_RECEIVED_TEMPLATE,
    LISTING_STATUS_SAVED_TEXT,
    LISTING_STATUS_SAVE_COUNT_TEMPLATE,
    LISTING_STATUS_SAVE_FAILED_TEXT,
    LISTING_STATUS_SAVING_TEXT,
    LISTING_STYLE,
    LISTING_TAB_ACTION_TEXT,
    LISTING_TAB_HERO_SUBTITLE,
    LISTING_TAB_HERO_TITLE,
)
from Listing.signals.signals import listing_signals
from settings import ASSETS_DIR

if TYPE_CHECKING:
    from .listing_manager_window import ListingManagerWindow

_LISTING_PROCESS_PAYLOAD_FILE_THRESHOLD_BYTES = 512 * 1024


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _normalized_account_platform(value: Any) -> str:
    return canonical_platform_code(value)


def _listing_fetch_page_size(account_rows: list[list[Any]]) -> int:
    environments = {
        _safe_str(row[5]).casefold()
        for row in account_rows
        if isinstance(row, (list, tuple)) and len(row) > 5
    }
    if environments & {"stage", "staging", "test", "sandbox"}:
        return LISTING_STAGE_FETCH_PAGE_SIZE
    return LISTING_DEFAULT_FETCH_PAGE_SIZE


def _platform_filter_options_from_account_platforms(account_platform_map: dict[int, Any]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    options: list[tuple[str, str]] = []
    for raw_value in account_platform_map.values():
        code = _normalized_account_platform(raw_value)
        if not code or code in seen:
            continue
        seen.add(code)
        label = platform_label_for_code(code) or ""
        if not label or label.casefold() == code.casefold():
            label = code.title()
        options.append((label, code))
    return sorted(options, key=lambda row: row[0].casefold())


def _cost_card_currency(card: dict[str, Any] | None, default: str = "TRY") -> str:
    code = _safe_str((card or {}).get("currency")).upper()
    fallback = _safe_str(default).upper()
    return code or fallback or "TRY"


def _compact_cost_row(row: dict) -> dict:
    from Listing.processors.pipeline import normalize_listing_cost_binding

    binding = normalize_listing_cost_binding(row)
    return {
        "cost_key": _safe_str(binding.get("cost_key")),
        "calculation_type": _safe_str(binding.get("calculation_type")) or None,
        "source_type": _safe_str(binding.get("source_type")) or None,
        "source_config": dict(binding.get("source_config") or {}) or None,
        "amount": binding.get("amount"),
        "quantity": binding.get("quantity"),
        "tariff_key": binding.get("tariff_key"),
    }


def _remove_stock_match_row_at(rows_data: list[dict], idx: int) -> list[dict]:
    rows = [dict(row or {}) for row in (rows_data or [])]
    if 0 <= idx < len(rows):
        rows.pop(idx)
    return rows


def _listing_badge_count_from_save_counts(counts: Any) -> int:
    if not isinstance(counts, dict):
        return 0
    total = 0
    for key in ("inserted", "updated", "deleted"):
        try:
            total += max(0, int(counts.get(key) or 0))
        except Exception:
            pass
    return total


def _listing_fetch_percent(current: int, total: int) -> int:
    try:
        total_i = int(total)
        current_i = int(current)
    except Exception:
        return 0
    if total_i <= 0:
        return 0
    return max(0, min(100, int(current_i / total_i * 100)))


def _prepare_listing_process_payload(payload: dict) -> tuple[dict, str | None]:
    try:
        raw = json.dumps(payload, ensure_ascii=False)
    except Exception:
        return dict(payload or {}), None

    if len(raw.encode("utf-8")) <= _LISTING_PROCESS_PAYLOAD_FILE_THRESHOLD_BYTES:
        return dict(payload or {}), None

    fd, temp_path = tempfile.mkstemp(prefix="orderscout_listing_payload_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        try:
            os.unlink(temp_path)
        except Exception:
            pass
        return dict(payload or {}), None

    return {"payload_path": temp_path}, temp_path

class ListingTab(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.list_window: Optional[ListingManagerWindow] = None
        self._fetch_progress_actual = 0
        self._fetch_progress_display = 0
        self._fetch_failed = False
        self._fetch_waiting_for_save = False
        self._payload_worker: SyncWorker | None = None

        self.setObjectName("ListingRoot")
        self.setStyleSheet(LISTING_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        hero = DashboardHeroCard(
            title=LISTING_TAB_HERO_TITLE,
            subtitle=LISTING_TAB_HERO_SUBTITLE,
            action_text=LISTING_TAB_ACTION_TEXT,
        )
        if hero.action_button is not None:
            hero.action_button.clicked.connect(self.open_listings_window)
        root.addWidget(hero)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)
        root.addLayout(content_row, 1)

        self._panel_sidebar = SplitPanelSidebar(self, sidebar_width=92)
        self._panel_sidebar.add_panel_button(
            "fetch",
            "",
            tooltip=str(ui_text("listing.sidebar.fetch_tooltip", "Veri çekme paneli")),
            icon_path=str(ASSETS_DIR / "veri-cekme.png"),
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
        self._left_stick_size = 520
        self._left_collapse_trigger = 480

        left_card = QFrame()
        left_card.setObjectName("SectionCard")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(14, 12, 14, 12)
        left_layout.setSpacing(10)

        left_layout.addWidget(QLabel(LISTING_FETCH_PANEL_TITLE, objectName="SectionTitle"))

        self.no_company_card = QFrame()
        self.no_company_card.setObjectName("QuickCard")
        no_company_layout = QVBoxLayout(self.no_company_card)
        no_company_layout.setContentsMargins(12, 10, 12, 10)
        no_company_layout.setSpacing(8)
        no_company_title = QLabel(str(ui_text("listing.fetch_panel.no_company_title", "Henüz şirket yok")), objectName="SectionTitle")
        self.no_company_hint = QLabel(
            str(
                ui_text(
                    "listing.fetch_panel.no_company_hint",
                    "İlan çekmeden önce en az bir şirket hesabı eklemelisin."
                )
            )
        )
        self.no_company_hint.setObjectName("Muted")
        self.no_company_hint.setWordWrap(True)
        self.btn_add_company = ActionPulseButton(
            text=str(ui_text("listing.fetch_panel.add_company_button", "Şirket Ekle")),
            center_text=True,
        )
        self.btn_add_company.setMinimumWidth(220)
        self.btn_add_company.setEnabled(True)
        self.btn_add_company.clicked.connect(self._open_company_manager_from_fetch_panel)
        no_company_layout.addWidget(no_company_title)
        no_company_layout.addWidget(self.no_company_hint)
        no_company_layout.addWidget(self.btn_add_company, alignment=Qt.AlignmentFlag.AlignLeft)
        left_layout.addWidget(self.no_company_card)

        self.company_list = CompanyListWidget()
        self.company_list.setMinimumWidth(260)
        self.company_list.companies_loaded.connect(lambda *_args: self._refresh_company_list_state())
        left_layout.addWidget(self.company_list)

        self.fetch_button = CircularProgressButton(LISTING_FETCH_BUTTON_TEXT, size_scale=1.2)
        if hasattr(self.fetch_button, "setAutoResetOnComplete"):
            self.fetch_button.setAutoResetOnComplete(False)
        self.fetch_button.clicked.connect(self.fetch_products)
        left_layout.addWidget(self.fetch_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        auto_card = QFrame()
        auto_card.setObjectName("QuickCard")
        auto_card.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        auto_card_layout = QHBoxLayout(auto_card)
        auto_card_layout.setContentsMargins(10, 8, 10, 8)
        auto_card_layout.setSpacing(10)

        auto_label = QLabel(LISTING_AUTO_FETCH_LABEL, objectName="Muted")
        self.auto_fetch_toggle = SwitchButton()
        self.auto_fetch_toggle.setChecked(False)
        self.auto_fetch_toggle.clicked.connect(self._toggle_auto_fetch)

        self.auto_fetch_minutes = NumberStepper(minimum=2, maximum=120, step=1)
        self.auto_fetch_minutes.setValue(2)
        self.auto_fetch_minutes.setEnabled(False)
        self.auto_fetch_minutes.setFixedWidth(90)
        self.auto_fetch_minutes.valueChanged.connect(self._on_auto_fetch_minutes_changed)

        unit_label = QLabel(LISTING_AUTO_FETCH_UNIT_TEXT, objectName="Muted")
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

        self.status_label = QLabel(LISTING_STATUS_IDLE_TEXT)
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)

        self._auto_fetch_interval = 120
        self.fetch_button.setRepeatInterval(self._auto_fetch_interval)
        account_signals.company_changed.connect(self._on_companies_changed)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_card)
        splitter.addWidget(left_scroll)

        right_card = QuickAccessSection(
            title=LISTING_QUICK_ACCESS_TITLE,
            subtitle=LISTING_QUICK_ACCESS_SUBTITLE,
        )
        right_layout = right_card.body_layout

        self.btn_open_products = BadgeButton(
            LISTING_BADGE_BUTTON_TEXT,
            icon_path=os.path.join(ASSETS_DIR, "ilanlar.png"),
            icon_size=48,
            size_scale=1.6632,
        )
        self.btn_open_products.setMinimumHeight(100)
        self.btn_open_products.clicked.connect(self.open_listings_window)
        listing_signals.badge_changed.connect(self._on_listing_badge_changed)
        listing_signals.badge_cleared.connect(self._on_listing_badge_cleared)
        listing_signals.fetch_started.connect(self._on_listing_fetch_started)
        listing_signals.products_loaded.connect(self._on_listing_products_loaded)
        listing_signals.products_save_started.connect(self._on_listing_products_save_started)
        listing_signals.products_saved.connect(self._on_listing_products_saved)
        listing_signals.products_save_failed.connect(self._on_listing_products_save_failed)
        self._fetch_from_auto_repeat = False

        right_layout.addWidget(self.btn_open_products, alignment=Qt.AlignmentFlag.AlignLeft)
        right_layout.addStretch(1)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setWidget(right_card)
        splitter.addWidget(right_scroll)
        splitter.setSizes([520, 1020])

        self._sync_sidebar_state_from_splitter()

    # ------------------------------------------------------------
    def _release_splitter_guard(self):
        self._splitter_guard = False
        self._sync_sidebar_state_from_splitter()

    def _is_fetch_panel_open(self) -> bool:
        sizes = self._tab_splitter.sizes()
        if len(sizes) < 2:
            return False
        return int(sizes[0]) > 8

    def _sync_sidebar_state_from_splitter(self):
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

    # ------------------------------------------------------------
    def _begin_fetch_progress(self) -> None:
        self._fetch_failed = False
        self._fetch_waiting_for_save = False
        self._fetch_progress_actual = 0
        self._fetch_progress_display = 0
        self.fetch_button.setProgress(0)

    def _stop_fetch_progress(self) -> None:
        return

    def _finish_fetch_progress(self, *, success: bool) -> None:
        self._fetch_waiting_for_save = False
        self._fetch_from_auto_repeat = False
        self._stop_fetch_progress()
        if success:
            self._fetch_progress_actual = 100
            self._fetch_progress_display = 100
            self.fetch_button.setProgress(100)
            QTimer.singleShot(550, self._reset_fetch_button_after_success)
            return
        self._fetch_failed = True
        self.fetch_button.fail()
        self.fetch_button.setEnabled(True)

    def _reset_fetch_button_after_success(self) -> None:
        self.fetch_button.reset()
        self.fetch_button.setEnabled(True)

    def _set_fetch_progress_actual(self, percent: int) -> None:
        target = max(0, min(int(percent), 99))
        self._fetch_progress_actual = target
        if target <= self._fetch_progress_display:
            return
        self._fetch_progress_display = target
        self.fetch_button.setProgress(self._fetch_progress_display)

    def fetch_products(self):
        from Account.views.actions import collect_selected_companies
        from Listing.views.actions import action_fetch_listings, action_get_company_credentials

        if self.company_list.count() == 0:
            self._refresh_company_list_state(reload_companies=True)
            MessageHandler.show(
                self,
                Result.fail(
                    str(ui_text("listing.fetch_panel.no_company_error", "Kayıtlı şirket bulunamadı. Önce şirket eklemelisin.")),
                    close_dialog=False,
                ),
                only_errors=True,
            )
            return

        if not self.fetch_button.isEnabled():
            return

        try:
            self._fetch_from_auto_repeat = bool(self.auto_fetch_toggle.isChecked())

            res_sel = collect_selected_companies(self.company_list)
            if not res_sel.success:
                self.fetch_button.fail()
                self.fetch_button.setEnabled(True)
                MessageHandler.show(self, res_sel, only_errors=True)
                return

            selected_pks = res_sel.data.get("selected_company_pks", []) or []
            res_creds = action_get_company_credentials(selected_pks)
            if not res_creds.success:
                self.fetch_button.fail()
                self.fetch_button.setEnabled(True)
                MessageHandler.show(self, res_creds, only_errors=True)
                return

            comp_api_account_list = res_creds.data.get("accounts", []) or []
            if not comp_api_account_list:
                self.fetch_button.fail()
                self.fetch_button.setEnabled(True)
                MessageHandler.show(self, Result.fail("Seçili mağazalar için API bilgisi yok."), only_errors=True)
                return
            account_records = res_creds.data.get("records", []) or []
            account_accept_language_map = {
                getattr(record, "pk", None): (
                    str((getattr(record, "extra_config", None) or {}).get("acceptLanguage") or "").strip()
                    if isinstance(getattr(record, "extra_config", None), dict)
                    else ""
                )
                for record in account_records
                if getattr(record, "pk", None) is not None
            }
            account_environment_map = {
                getattr(record, "pk", None): (
                    str(
                        (getattr(record, "extra_config", None) or {}).get("environment")
                        or (getattr(record, "extra_config", None) or {}).get("api_environment")
                        or "production"
                    ).strip()
                    if isinstance(getattr(record, "extra_config", None), dict)
                    else "production"
                )
                for record in account_records
                if getattr(record, "pk", None) is not None
            }
            comp_api_account_list = [
                list(raw_row[:4])
                + [
                    account_accept_language_map.get(raw_row[0], ""),
                    account_environment_map.get(raw_row[0], "production"),
                ]
                for raw_row in comp_api_account_list
                if isinstance(raw_row, (list, tuple)) and len(raw_row) >= 4
            ]
            if not comp_api_account_list:
                self.fetch_button.fail()
                self.fetch_button.setEnabled(True)
                MessageHandler.show(self, Result.fail("Seçili mağazalar için API context bilgisi yok."), only_errors=True)
                return

            fetch_page_size = _listing_fetch_page_size(comp_api_account_list)

            self.status_label.setText(LISTING_STATUS_FETCHING_TEXT)
            listing_signals.fetch_started.emit(
                {
                    "account_ids": list(selected_pks),
                    "account_count": len(selected_pks),
                    "fetch_all_pages": True,
                    "page_size": fetch_page_size,
                }
            )
            self.fetch_button.setEnabled(False)
            self.fetch_button.start()
            self._begin_fetch_progress()

            params = {
                "page": 0,
                "size": fetch_page_size,
                "approved": None,
                "barcode": None,
                "stock_code": None,
                "fetch_all_pages": True,
                "max_pages": None,
            }

            self.worker = AsyncWorker(
                action_fetch_listings,
                comp_api_account_list,
                parent=self,
                kwargs=params,
            )
            self.worker.progress_changed.connect(self._on_progress)
            self.worker.result_ready.connect(self._on_fetch_done)
            self.worker.finished.connect(self._on_worker_finished)
            self.worker.start()

        except Exception as e:
            self.fetch_button.fail()
            self.fetch_button.setEnabled(True)
            MessageHandler.show(self, Result.fail(map_error_to_message(e), error=e), only_errors=True)

    def _on_progress(self, current: int, total: int):
        try:
            total = int(total)
            if total <= 0:
                return
            percent = _listing_fetch_percent(current, total)
            self._set_fetch_progress_actual(percent)
        except Exception:
            pass

    def _on_fetch_done(self, result: Result):
        if not result.success:
            self._fetch_failed = True
            self._stop_fetch_progress()
            self.fetch_button.fail()
            self.fetch_button.setEnabled(True)
            self.status_label.setText(f"Hata: {result.message}")
            MessageHandler.show(self, result, only_errors=True)
            return

        self._fetch_waiting_for_save = True

        items = (result.data or {}).get("items", []) or []
        listing_signals.products_loaded.emit(
            {
                "count": len(items),
                "api_account_ids": list((result.data or {}).get("api_account_ids", []) or []),
            }
        )
        self.status_label.setText(LISTING_STATUS_SAVING_TEXT)

        payload = {
            "items": items,
            "sync_api_account_ids": (result.data or {}).get("api_account_ids", []) or [],
            "prune_missing": True,
        }
        listing_signals.products_save_started.emit(
            {
                "count": len(items),
                "api_account_ids": list(payload["sync_api_account_ids"]),
                "prune_missing": True,
            }
        )

        def _start_db_save(process_payload: dict, payload_path: str | None) -> None:
            target = ProcessTarget(identifier="Listing/processors/trendyol/db_save_worker.py")
            self.db_runner = GenericProcessRunner(target=target, initial_payload=process_payload, parent=self)
            self.db_runner.finished.connect(lambda result: _on_db_finished(result, payload_path))
            self.db_runner.start()
            self.db_runner.close_stdin()

        def _on_payload_ready(result: Result) -> None:
            self._payload_worker = None
            if not result.success:
                self._fetch_failed = True
                self._finish_fetch_progress(success=False)
                self.status_label.setText(LISTING_STATUS_SAVE_FAILED_TEXT)
                MessageHandler.show(self, result, only_errors=True)
                return
            prepared = (result.data or {}).get("result")
            if not isinstance(prepared, tuple) or len(prepared) != 2:
                prepared = (dict(payload or {}), None)
            process_payload, payload_path = prepared
            _start_db_save(dict(process_payload or {}), payload_path)

        def _on_db_finished(result: dict, payload_path: str | None):
            if payload_path:
                try:
                    os.unlink(payload_path)
                except Exception:
                    pass
            failed = not bool(result.get("success"))
            if failed:
                listing_signals.products_save_failed.emit(
                    {
                        "message": result.get("message", "DB kayıt hatası."),
                        "api_account_ids": list(payload["sync_api_account_ids"]),
                    }
                )
            if not result.get("success"):
                MessageHandler.show(self, Result.fail(result.get("message", "DB kayıt hatası.")), only_errors=True)
                self.status_label.setText(LISTING_STATUS_SAVE_FAILED_TEXT)
                self._finish_fetch_progress(success=False)
                return

            data = result.get("data") or {}
            listing_signals.products_saved.emit(
                {
                    "attempted": data.get("attempted"),
                    "changed": bool(data.get("changed")),
                    "counts": dict(data.get("counts") or {}),
                    "api_account_ids": list(payload["sync_api_account_ids"]),
                }
            )
            changed = bool(data.get("changed"))
            if changed:
                self.status_label.setText(LISTING_STATUS_SAVED_TEXT)
                if self.list_window is not None and self.list_window.isVisible():
                    self.list_window.mark_stale()
                counts = data.get("counts") or {}
                delta = _listing_badge_count_from_save_counts(counts)
                if delta > 0:
                    listing_signals.badge_changed.emit(delta)
                else:
                    listing_signals.badge_cleared.emit()
            else:
                self.status_label.setText(LISTING_STATUS_NO_CHANGES_TEXT)
                listing_signals.badge_cleared.emit()
            self._finish_fetch_progress(success=True)

        worker = SyncWorker(_prepare_listing_process_payload, payload, parent=self)
        self._payload_worker = worker
        worker.result_ready.connect(_on_payload_ready)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_worker_finished(self):
        self._fetch_from_auto_repeat = False
        self._stop_fetch_progress()
        if self._fetch_waiting_for_save or self._fetch_failed:
            return
        self.fetch_button.setEnabled(True)
        delay_ms = 550 if not self._fetch_failed and self._fetch_progress_display >= 100 else 0
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, self.fetch_button.reset)
        else:
            self.fetch_button.reset()

    def open_listings_window(self):
        try:
            from .listing_manager_window import ListingManagerWindow

            if self.list_window is None:
                self.list_window = ListingManagerWindow(company_list_ref=self.company_list)
            self.list_window.showMaximized()
            self.list_window.raise_()
            self.list_window.activateWindow()
            listing_signals.badge_cleared.emit()
        except Exception as e:
            res = Result.fail(map_error_to_message(e), error=e, close_dialog=False)
            MessageHandler.show(self, res, only_errors=True)

    def _toggle_auto_fetch(self):
        try:
            if self.auto_fetch_toggle.isChecked():
                self.auto_fetch_minutes.setEnabled(True)
                self._on_auto_fetch_minutes_changed(self.auto_fetch_minutes.value())
                self.fetch_button.enableRepeat(True)
                mins = self.auto_fetch_minutes.value()
                self.status_label.setText(LISTING_AUTO_FETCH_ACTIVE_TEMPLATE.format(mins=mins))
            else:
                self.auto_fetch_minutes.setEnabled(False)
                self.fetch_button.stopRepeat()
                self.status_label.setText(LISTING_AUTO_FETCH_STOPPED_TEXT)
        except Exception:
            pass

    def _on_auto_fetch_minutes_changed(self, value: int):
        try:
            mins = max(2, int(value))
            self._auto_fetch_interval = mins * 60
            self.fetch_button.setRepeatInterval(self._auto_fetch_interval)
            if self.auto_fetch_toggle.isChecked():
                self.status_label.setText(LISTING_AUTO_FETCH_ACTIVE_TEMPLATE.format(mins=mins))
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
                            "listing.fetch_panel.no_company_status",
                            "Henüz ekli şirket yok. Şirket ekleyerek ilan çekmeye başlayabilirsin."
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
                    "listing.fetch_panel.no_company_status",
                    "Henüz ekli şirket yok. Şirket ekleyerek ilan çekmeye başlayabilirsin."
                )
            )
            if self.status_label.text().strip() == empty_status:
                self.status_label.setText(str(ui_text("listing.fetch_panel.idle_status", LISTING_STATUS_IDLE_TEXT)))
        except Exception:
            pass

    def _on_listing_fetch_started(self, payload: Any):
        if not isinstance(payload, dict):
            self.status_label.setText(LISTING_STATUS_FETCHING_TEXT)
            return
        account_count = max(0, int(payload.get("account_count") or 0))
        if account_count > 0:
            self.status_label.setText(LISTING_STATUS_FETCHING_COUNT_TEMPLATE.format(account_count=account_count))
        else:
            self.status_label.setText(LISTING_STATUS_FETCHING_TEXT)

    def _on_listing_products_loaded(self, payload: Any):
        if not isinstance(payload, dict):
            return
        count = max(0, int(payload.get("count") or 0))
        self.status_label.setText(
            LISTING_STATUS_PRODUCTS_RECEIVED_TEMPLATE.format(count=count)
            if count > 0
            else LISTING_STATUS_PRODUCTS_EMPTY_TEXT
        )

    def _on_listing_products_save_started(self, payload: Any):
        if not isinstance(payload, dict):
            self.status_label.setText(LISTING_STATUS_SAVING_TEXT)
            return
        count = max(0, int(payload.get("count") or 0))
        self.status_label.setText(
            LISTING_STATUS_SAVE_COUNT_TEMPLATE.format(count=count)
            if count > 0
            else LISTING_STATUS_SAVING_TEXT
        )

    def _on_listing_products_saved(self, payload: Any):
        data = dict(payload or {}) if isinstance(payload, dict) else {}
        changed = bool(data.get("changed"))
        if changed:
            self.status_label.setText(LISTING_STATUS_SAVED_TEXT)
        else:
            self.status_label.setText(LISTING_STATUS_NO_CHANGES_TEXT)

    def _on_listing_products_save_failed(self, payload: Any):
        data = dict(payload or {}) if isinstance(payload, dict) else {}
        self.status_label.setText(_safe_str(data.get("message")) or LISTING_STATUS_SAVE_FAILED_TEXT)

    def _on_listing_badge_changed(self, count: int):
        try:
            self.btn_open_products.setBadgeCount(int(count))
            self.btn_open_products.setActive(True)
        except Exception:
            pass

    def _on_listing_badge_cleared(self):
        try:
            self.btn_open_products.setBadgeCount(0)
            self.btn_open_products.setActive(True)
        except Exception:
            pass








