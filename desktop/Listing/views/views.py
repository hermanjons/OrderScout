from __future__ import annotations

import json
import os
import tempfile
from typing import TYPE_CHECKING, Any, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from Core.services.business_refresh import business_refresh_signals
from Account.signals.signals import account_signals
from Account.views.company_list_widget import CompanyListWidget
from Core.views import ActionPulseButton, BadgeButton, ResettableSplitter
from Core.views.tab_widgets import DashboardHeroCard, QuickAccessSection, SplitPanelSidebar
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from Listing.constants import (
    LISTING_DEFAULT_FETCH_PAGE_SIZE,
    LISTING_STAGE_FETCH_PAGE_SIZE,
    ui_text,
)
from Listing.constants.platform_constants import canonical_platform_code, platform_label_for_code
from Listing.constants.ui_constants import (
    LISTING_BADGE_BUTTON_TEXT,
    LISTING_QUICK_ACCESS_SUBTITLE,
    LISTING_QUICK_ACCESS_TITLE,
    LISTING_STATUS_FETCHING_COUNT_TEMPLATE,
    LISTING_STATUS_FETCHING_TEXT,
    LISTING_STATUS_NO_CHANGES_TEXT,
    LISTING_STATUS_PRODUCTS_EMPTY_TEXT,
    LISTING_STATUS_PRODUCTS_RECEIVED_TEMPLATE,
    LISTING_STATUS_SAVED_TEXT,
    LISTING_STATUS_SAVE_COUNT_TEMPLATE,
    LISTING_STATUS_SAVE_FAILED_TEXT,
    LISTING_STATUS_SAVING_TEXT,
    LISTING_STYLE,
    LISTING_TAB_ACTION_TEXT,
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

        self.setObjectName("ListingRoot")
        self.setStyleSheet(LISTING_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        hero = DashboardHeroCard(
            title=LISTING_TAB_HERO_TITLE,
            subtitle="Kayıtlar arka planda otomatik güncellenir.",
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
            tooltip=str(ui_text("listing.sidebar.fetch_tooltip", "Otomatik güncelleme durumu")),
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

        left_layout.addWidget(QLabel("Otomatik Güncelleme", objectName="SectionTitle"))

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

        self.status_label = QLabel("Otomatik güncelleme hazır.")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)

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
        business_refresh_signals.status_changed.connect(self._on_background_status)
        business_refresh_signals.refreshed.connect(self._on_background_refreshed)
        self.status_label.setText(business_refresh_signals.statuses.get("listing", "Otomatik güncelleme hazır."))

    # ------------------------------------------------------------
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
        if domain == "listing":
            self.status_label.setText(message)

    def _on_background_refreshed(self, domain: str, payload: object) -> None:
        if domain != "listing":
            return
        if self.list_window is not None:
            self.list_window.mark_stale()

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


