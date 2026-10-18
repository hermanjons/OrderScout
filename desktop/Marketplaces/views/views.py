from __future__ import annotations

import weakref
from typing import Optional

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from Core.threads.sync_worker import SyncWorker
from Core.views import BadgeButton, ResettableSplitter
from Core.views.tab_widgets import DashboardHeroCard, QuickAccessSection, SplitPanelSidebar
from Marketplaces.constants.ui_constants import (
    MARKETPLACES_BADGE_BUTTON_TEXT,
    MARKETPLACES_HERO_SUBTITLE,
    MARKETPLACES_HERO_TITLE,
    MARKETPLACES_INFO_HINT,
    MARKETPLACES_INFO_TITLE,
    MARKETPLACES_PANEL_TITLE,
    MARKETPLACES_PANEL_TOOLTIP,
    MARKETPLACES_QUICK_ACCESS_SUBTITLE,
    MARKETPLACES_QUICK_ACCESS_TITLE,
    MARKETPLACES_TAB_STYLE,
)
from Marketplaces.signals.signals import marketplace_signals
from settings import ASSETS_DIR


def load_marketplaces(*args, **kwargs):
    from Marketplaces.views.actions import load_marketplaces

    return load_marketplaces(*args, **kwargs)


def _load_marketplaces_summary_state():
    return load_marketplaces(source_filter="pending")


def _marketplaces_icon_path() -> str:
    for name in ("marketplaces-icon.png", "anlik-durum-icon.png", "duzenleme-icon.png"):
        path = ASSETS_DIR / name
        if path.exists():
            return str(path)
    return str(ASSETS_DIR / "marketplaces-icon.png")


class MarketplacesTab(QWidget):
    _signal_bound_tab_ref: "weakref.ReferenceType[MarketplacesTab] | None" = None

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("MarketplacesRoot")
        self.setStyleSheet(MARKETPLACES_TAB_STYLE)

        self.marketplaces_window: Optional[QWidget] = None
        self._splitter_guard = False
        self._left_stick_size = 520
        self._left_collapse_trigger = 480
        self._summary_bootstrapped = False
        self._summary_refresh_pending = False
        self._summary_worker: SyncWorker | None = None
        self._quick_badge_count = 0
        self._pending_current_count = 0
        self._pending_seen_count = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        hero = DashboardHeroCard(
            title=MARKETPLACES_HERO_TITLE,
            subtitle=MARKETPLACES_HERO_SUBTITLE,
        )
        root.addWidget(hero)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)
        root.addLayout(content_row, 1)

        self._panel_sidebar = SplitPanelSidebar(self, sidebar_width=92)
        self._panel_sidebar.add_panel_button(
            "panel",
            "",
            tooltip=MARKETPLACES_PANEL_TOOLTIP,
            icon_path=str(ASSETS_DIR / "duzenleme-icon.png"),
            shape="circular",
            icon_scale=1.28,
        )
        self._panel_sidebar.panel_toggled.connect(self._on_panel_sidebar_toggled)
        content_row.addWidget(self._panel_sidebar)

        self._tab_splitter = ResettableSplitter(Qt.Orientation.Horizontal)
        self._tab_splitter.setChildrenCollapsible(True)
        self._tab_splitter.setHandleWidth(6)
        self._tab_splitter.splitterMoved.connect(self._on_tab_splitter_moved)
        content_row.addWidget(self._tab_splitter, 1)

        left_card = QFrame(self)
        left_card.setObjectName("SectionCard")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(14, 12, 14, 12)
        left_layout.setSpacing(10)
        left_layout.addWidget(QLabel(MARKETPLACES_PANEL_TITLE, objectName="SectionTitle"))

        info_card = QFrame(self)
        info_card.setObjectName("QuickCard")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(12, 10, 12, 10)
        info_layout.setSpacing(8)
        info_layout.addWidget(QLabel(MARKETPLACES_INFO_TITLE, objectName="SectionTitle"))
        hint = QLabel(MARKETPLACES_INFO_HINT, objectName="Muted")
        hint.setWordWrap(True)
        info_layout.addWidget(hint)
        left_layout.addWidget(info_card)
        left_layout.addStretch(1)

        left_scroll = QScrollArea(self)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_card)
        self._tab_splitter.addWidget(left_scroll)

        right_card = QuickAccessSection(
            title=MARKETPLACES_QUICK_ACCESS_TITLE,
            subtitle=MARKETPLACES_QUICK_ACCESS_SUBTITLE,
            parent=self,
        )
        right_layout = right_card.body_layout

        self.btn_marketplaces = BadgeButton(
            MARKETPLACES_BADGE_BUTTON_TEXT,
            icon_path=_marketplaces_icon_path(),
            icon_size=48,
            size_scale=1.6632,
        )
        self.btn_marketplaces.setMinimumHeight(100)
        self.btn_marketplaces.clicked.connect(self.open_marketplaces_window)
        right_layout.addWidget(self.btn_marketplaces)
        right_layout.addStretch(1)

        self._tab_splitter.addWidget(right_card)
        self._tab_splitter.setCollapsible(0, True)
        self._tab_splitter.setCollapsible(1, False)
        self._tab_splitter.setSizes([0, 1280])
        self._sync_sidebar_state_from_splitter()
        previous_ref = type(self)._signal_bound_tab_ref
        previous_tab = previous_ref() if previous_ref is not None else None
        if previous_tab is not None and previous_tab is not self:
            try:
                marketplace_signals.marketplaces_changed.disconnect(previous_tab._on_marketplaces_changed)
            except Exception:
                pass
        marketplace_signals.marketplaces_changed.connect(self._on_marketplaces_changed)
        type(self)._signal_bound_tab_ref = weakref.ref(self)
        self._apply_marketplaces_badge()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._summary_bootstrapped:
            return
        self._summary_bootstrapped = True
        QTimer.singleShot(0, self._refresh_summary_async)

    def closeEvent(self, event) -> None:
        worker = self._summary_worker
        if worker is not None and worker.isRunning():
            worker.quit()
            worker.wait(1500)
        super().closeEvent(event)

    def _splitter_total_size(self) -> int:
        sizes = self._tab_splitter.sizes()
        total = int(sum(sizes)) if sizes else 0
        if total > 0:
            return total
        width = int(self._tab_splitter.width() or 0)
        return width if width > 0 else 1380

    def _is_left_panel_open(self) -> bool:
        sizes = self._tab_splitter.sizes()
        return len(sizes) >= 2 and int(sizes[0]) > 8

    def _release_splitter_guard(self) -> None:
        self._splitter_guard = False
        self._sync_sidebar_state_from_splitter()

    def _sync_sidebar_state_from_splitter(self) -> None:
        self._panel_sidebar.set_active_panel("panel" if self._is_left_panel_open() else None)

    def _open_left_panel(self) -> None:
        if self._is_left_panel_open():
            self._sync_sidebar_state_from_splitter()
            return
        total = self._splitter_total_size()
        left = max(360, min(self._left_stick_size, total - 320))
        self._splitter_guard = True
        self._tab_splitter.setSizes([left, max(0, total - left)])
        QTimer.singleShot(0, self._release_splitter_guard)

    def _close_left_panel(self) -> None:
        if not self._is_left_panel_open():
            self._sync_sidebar_state_from_splitter()
            return
        total = self._splitter_total_size()
        self._splitter_guard = True
        self._tab_splitter.setSizes([0, total])
        QTimer.singleShot(0, self._release_splitter_guard)

    def _on_panel_sidebar_toggled(self, panel_id: str, active: bool) -> None:
        if panel_id != "panel":
            return
        if active:
            self._open_left_panel()
        else:
            self._close_left_panel()

    def _on_tab_splitter_moved(self, pos: int, _index: int) -> None:
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
                self._splitter_guard = True
                self._tab_splitter.setSizes([0, total])
                QTimer.singleShot(0, self._release_splitter_guard)
                return
            self._splitter_guard = True
            self._tab_splitter.setSizes([self._left_stick_size, max(0, total - self._left_stick_size)])
            QTimer.singleShot(0, self._release_splitter_guard)
        except Exception:
            self._splitter_guard = False
        self._sync_sidebar_state_from_splitter()

    def _refresh_summary(self) -> None:
        try:
            result = load_marketplaces(source_filter="pending")
        except Exception:
            return
        self._apply_summary_result(result)

    def _refresh_summary_async(self) -> None:
        worker = self._summary_worker
        if worker is not None and worker.isRunning():
            self._summary_refresh_pending = True
            return

        self._summary_refresh_pending = False
        worker = SyncWorker(_load_marketplaces_summary_state, parent=self)
        self._summary_worker = worker
        worker.result_ready.connect(self._on_summary_result)
        worker.finished.connect(self._on_summary_finished)
        worker.start()

    def _on_summary_result(self, result) -> None:
        self._apply_summary_result(result)

    def _on_summary_finished(self) -> None:
        worker = self._summary_worker
        if worker is not None:
            worker.deleteLater()
        self._summary_worker = None
        if self._summary_refresh_pending:
            self._summary_refresh_pending = False
            QTimer.singleShot(0, self._refresh_summary_async)

    def _apply_summary_result(self, result) -> None:
        if not getattr(result, "success", False):
            return
        records = (getattr(result, "data", None) or {}).get("records") or []
        self._sync_marketplaces_pending_badge(len(records))

    def _apply_marketplaces_badge(self) -> None:
        self.btn_marketplaces.setBadgeCount(int(self._quick_badge_count))
        self.btn_marketplaces.setActive(True)

    def _clear_marketplaces_badge(self) -> None:
        self._pending_seen_count = max(0, int(self._pending_current_count))
        self._quick_badge_count = 0
        self._apply_marketplaces_badge()

    def _sync_marketplaces_pending_badge(self, pending_count: int) -> None:
        current = max(0, int(pending_count or 0))
        self._pending_current_count = current
        if self._is_marketplaces_window_visible():
            self._pending_seen_count = current
            self._quick_badge_count = 0
        else:
            self._pending_seen_count = min(max(0, int(self._pending_seen_count)), current)
            self._quick_badge_count = max(0, current - self._pending_seen_count)
        self._apply_marketplaces_badge()

    def _is_marketplaces_window_visible(self) -> bool:
        return bool(self.marketplaces_window is not None and self.marketplaces_window.isVisible())

    def _on_marketplaces_changed(self) -> None:
        QTimer.singleShot(0, self._refresh_summary)

    def open_marketplaces_window(self) -> None:
        if self.marketplaces_window is None:
            from .marketplaces_manager_window import MarketplacesWindow

            self.marketplaces_window = MarketplacesWindow()
            self.marketplaces_window.itemsChanged.connect(self._refresh_summary)
            self.marketplaces_window.destroyed.connect(lambda *_: setattr(self, "marketplaces_window", None))
        self._clear_marketplaces_badge()
        self.marketplaces_window.showMaximized()
        self.marketplaces_window.raise_()
        self.marketplaces_window.activateWindow()
        self._refresh_summary()
