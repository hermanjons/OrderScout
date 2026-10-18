from __future__ import annotations

from importlib import import_module
from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from Core.views import AppMessageCenter, BadgeButton, QuickAccessSection
from Core.views.tab_widgets import DashboardHeroCard
from Stock.constants.ui_constants import MODERN_LIGHT_QSS
from Stock.signals.signals import stock_signals
from settings import ASSETS_DIR


_DIALOG_EXPORTS = {
    "StockItemManagerDialog": ".stock_item_manager_dialog",
    "WarehouseManagerDialog": ".warehouse_manager_dialog",
    "SubGroupManagerDialog": ".sub_group_manager_dialog",
    "UpperGroupManagerDialog": ".upper_group_manager_dialog",
    "StockTxDialog": ".stock_tx_dialog",
    "StockOverviewDialog": ".stock_overview_dialog",
}


def _load_dialog_class(name: str):
    module_name = _DIALOG_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"Unknown stock dialog: {name}")
    module = import_module(module_name, "Stock.views")
    return getattr(module, name)


class StockTab(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StockRoot")
        self.setStyleSheet(MODERN_LIGHT_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        header = DashboardHeroCard(
            title="Envanter / Stok Yönetimi",
            subtitle="Stok kartları • Depolar • Giriş/Çıkış • Anlık durum",
            action_text="Anlık Durum",
        )
        if header.action_button is not None:
            header.action_button.clicked.connect(self.open_overview)
        root.addWidget(header)

        wrap = QuickAccessSection(
            title="Hızlı Erişim",
            subtitle="Stok kartları, hareketler ve grup tanımlarını ayrı pencerede aç.",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.btn_items = self._build_quick_access_button("Stok Kartları", "stock-cards-icon.png")
        self.btn_tx = self._build_quick_access_button("Stok Giriş/Çıkış", "stock-in-out.png")
        self.btn_warehouses = self._build_quick_access_button("Depolar", "depo-icon.png")
        self.btn_upper_groups = self._build_quick_access_button("Üst Gruplar", "stock-upper-groups-icon.png")
        self.btn_sub_groups = self._build_quick_access_button("Alt Gruplar", "stock-sub-groups-icon.png")

        self.btn_items.clicked.connect(self.open_items)
        self.btn_tx.clicked.connect(self.open_tx)
        self.btn_warehouses.clicked.connect(self.open_warehouses)
        self.btn_upper_groups.clicked.connect(self.open_upper_groups)
        self.btn_sub_groups.clicked.connect(self.open_sub_groups)

        grid.addWidget(self.btn_items, 0, 0)
        grid.addWidget(self.btn_tx, 0, 1)
        grid.addWidget(self.btn_warehouses, 0, 2)
        grid.addWidget(self.btn_upper_groups, 1, 0)
        grid.addWidget(self.btn_sub_groups, 1, 1)

        wrap.body_layout.addLayout(grid)
        root.addWidget(wrap)
        root.addStretch(1)

        self._quick_badges = {
            "items": 0,
            "tx": 0,
            "warehouses": 0,
            "upper_groups": 0,
            "sub_groups": 0,
        }
        self._quick_open_sections: set[str] = set()
        self._open_dialogs: list[Any] = []
        stock_signals.quick_access_changed.connect(self._on_quick_access_changed)
        self._apply_quick_access_badges()

    def _build_quick_access_button(self, text: str, icon_name: str) -> BadgeButton:
        icon_file = ASSETS_DIR / icon_name
        icon_path = str(icon_file) if icon_file.exists() else None
        btn = BadgeButton(
            text,
            icon_path=icon_path,
            icon_size=48,
            size_scale=1.6632,
        )
        btn.setMinimumHeight(100)
        btn.setBadgeCount(0)
        return btn

    @staticmethod
    def _normalize_quick_key(key: Any) -> Optional[str]:
        raw = str(key or "").strip().lower()
        if raw in {"item", "items", "stock_item", "stock_items"}:
            return "items"
        if raw in {"tx", "transaction", "transactions", "stock_tx", "stock_txs"}:
            return "tx"
        if raw in {"warehouse", "warehouses"}:
            return "warehouses"
        if raw in {"upper_group", "upper_groups", "ust_grup", "ust_gruplar"}:
            return "upper_groups"
        if raw in {"sub_group", "sub_groups", "subgroup", "subgroups", "alt_grup", "alt_gruplar"}:
            return "sub_groups"
        return None

    def _apply_quick_access_badges(self) -> None:
        self.btn_items.setBadgeCount(int(self._quick_badges.get("items", 0)))
        self.btn_tx.setBadgeCount(int(self._quick_badges.get("tx", 0)))
        self.btn_warehouses.setBadgeCount(int(self._quick_badges.get("warehouses", 0)))
        self.btn_upper_groups.setBadgeCount(int(self._quick_badges.get("upper_groups", 0)))
        self.btn_sub_groups.setBadgeCount(int(self._quick_badges.get("sub_groups", 0)))

    def _clear_quick_badge(self, key: str) -> None:
        norm = self._normalize_quick_key(key)
        if not norm:
            return
        self._quick_badges[norm] = 0
        self._apply_quick_access_badges()

    def _on_quick_access_changed(self, section: str, delta: int) -> None:
        norm = self._normalize_quick_key(section)
        if not norm:
            return
        if norm in self._quick_open_sections:
            self._quick_badges[norm] = 0
        else:
            add = max(1, int(delta or 1))
            self._quick_badges[norm] = max(0, int(self._quick_badges.get(norm, 0)) + add)
        self._apply_quick_access_badges()

    def _mark_quick_section_open(self, key: str, dialog: Any) -> None:
        norm = self._normalize_quick_key(key)
        if not norm:
            return
        self._quick_open_sections.add(norm)
        self._clear_quick_badge(norm)

        def _on_closed(_obj=None):
            self._quick_open_sections.discard(norm)
            self._clear_quick_badge(norm)

        dialog.finished.connect(lambda _code=0: _on_closed())
        dialog.destroyed.connect(_on_closed)

    def _retain_open_dialog(self, dialog: Any) -> None:
        self._open_dialogs.append(dialog)

        def _release(_obj=None, dlg=dialog):
            try:
                self._open_dialogs.remove(dlg)
            except ValueError:
                pass

        dialog.finished.connect(lambda _code=0, dlg=dialog: _release(dlg))
        dialog.destroyed.connect(lambda _obj=None, dlg=dialog: _release(dlg))

    def _open_full_dialog(
        self,
        dialog_cls,
        dialog_name: str,
        quick_key: Optional[str] = None,
        quick_icon_name: Optional[str] = None,
    ):
        try:
            dlg = dialog_cls(self)
            if quick_icon_name:
                icon_file = ASSETS_DIR / str(quick_icon_name)
                if icon_file.exists():
                    dlg.setWindowIcon(QIcon(str(icon_file)))
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._retain_open_dialog(dlg)
            if quick_key:
                self._mark_quick_section_open(quick_key, dlg)
            dlg.open_full()
        except Exception as e:
            AppMessageCenter.error(self, "Hata", f"{dialog_name} açılamadı.\n{e}")

    def open_items(self):
        self._open_full_dialog(
            _load_dialog_class("StockItemManagerDialog"),
            "Stok Kartları",
            quick_key="items",
            quick_icon_name="stock-cards-icon.png",
        )

    def open_tx(self):
        self._open_full_dialog(
            _load_dialog_class("StockTxDialog"),
            "Stok Giriş/Çıkış",
            quick_key="tx",
            quick_icon_name="stock-in-out.png",
        )

    def open_warehouses(self):
        self._open_full_dialog(
            _load_dialog_class("WarehouseManagerDialog"),
            "Depolar",
            quick_key="warehouses",
            quick_icon_name="depo-icon.png",
        )

    def open_upper_groups(self):
        self._open_full_dialog(
            _load_dialog_class("UpperGroupManagerDialog"),
            "Üst Gruplar",
            quick_key="upper_groups",
            quick_icon_name="stock-upper-groups-icon.png",
        )

    def open_sub_groups(self):
        self._open_full_dialog(
            _load_dialog_class("SubGroupManagerDialog"),
            "Alt Gruplar",
            quick_key="sub_groups",
            quick_icon_name="stock-sub-groups-icon.png",
        )

    def open_overview(self):
        self._open_full_dialog(_load_dialog_class("StockOverviewDialog"), "Anlık Durum")


__all__ = ["StockTab"]
