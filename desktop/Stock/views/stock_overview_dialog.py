from __future__ import annotations
from .views import *
from Feedback.processors.pipeline import Result


def _load_stock_overview_payload(*, warehouse_id=None) -> Result:
    items_res = action_list_items()
    if not items_res.success:
        return items_res
    wh_res = action_list_warehouses()
    if not wh_res.success:
        return wh_res
    balances_res = action_list_item_balances(warehouse_id=warehouse_id, only_active=True)
    if not balances_res.success:
        return balances_res
    return Result.ok(
        "Stok ozeti hazirlandi.",
        close_dialog=False,
        data={
            "items": (items_res.data or {}).get("records", []) or [],
            "warehouses": (wh_res.data or {}).get("records", []) or [],
            "balances": (balances_res.data or {}).get("records", []) or [],
        },
    )


def _load_stock_summary_payload(*, warehouse_id=None) -> Result:
    res = action_list_item_balances(warehouse_id=warehouse_id, only_active=True)
    if not res.success:
        return res
    return Result.ok(
        "Stok ozeti hazirlandi.",
        close_dialog=False,
        data={"balances": (res.data or {}).get("records", []) or []},
    )

class StockOverviewDialog(FullscreenDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Anlık Stok Durumu")
        self._has_loaded_once = False
        self._refresh_worker: SyncWorker | None = None
        self._summary_worker: SyncWorker | None = None
        self._summary_seq = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        card = QFrame(); card.setObjectName("Card")
        cl = QVBoxLayout(card); cl.setContentsMargins(16, 16, 16, 16); cl.setSpacing(10)

        row = QHBoxLayout()
        self.cb_item = SwitchSelectWidget(multi=False, all_text="Seçiniz")
        self.cb_wh = SwitchSelectWidget(multi=False, all_text="Seçiniz")
        row.addWidget(QLabel("Ürün:"))
        row.addWidget(self.cb_item, 2)
        row.addSpacing(10)
        row.addWidget(QLabel("Depo:"))
        row.addWidget(self.cb_wh, 2)
        cl.addLayout(row)

        self.lbl = QLabel("Stok: -")
        self.lbl.setObjectName("Title")
        cl.addWidget(self.lbl)

        summary = QFrame(); summary.setObjectName("SoftCard")
        sl = QVBoxLayout(summary); sl.setContentsMargins(12, 12, 12, 12); sl.setSpacing(8)

        tools = QHBoxLayout()
        self.le_sum_search = QLineEdit()
        self.le_sum_search.setObjectName("Search")
        self.le_sum_search.setPlaceholderText("Ara: sku / ad / barkod / marka / kategori")
        self.chk_low = QCheckBox("Kritik stoklar")
        self.btn_refresh_summary = _btn(STOCK_MANAGER_REFRESH_TEXT, "Secondary", 40)
        self.btn_refresh_summary.clicked.connect(self.refresh_summary)
        tools.addWidget(self.le_sum_search, 2)
        tools.addWidget(self.chk_low, 0)
        tools.addWidget(self.btn_refresh_summary, 0)
        sl.addLayout(tools)

        self.table = ExcelTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["SKU", "Ad", "Bakiye", "Min", "Durum", "Kategori"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        sl.addWidget(self.table)

        cl.addWidget(summary)

        outer.addWidget(card)
        outer.addStretch(1)

        self.cb_item.currentIndexChanged.connect(self.calculate)
        self.cb_wh.currentIndexChanged.connect(self.calculate)
        self.le_sum_search.textChanged.connect(self._apply_summary_filter)
        self.chk_low.stateChanged.connect(self._apply_summary_filter)

    def showEvent(self, event):
        super().showEvent(event)
        if self._has_loaded_once:
            return
        self._has_loaded_once = True
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        worker = self._refresh_worker
        if worker is not None and worker.isRunning():
            return
        self.btn_refresh_summary.setEnabled(False)
        self.btn_refresh_summary.setText("Yukleniyor...")
        worker = SyncWorker(_load_stock_overview_payload, parent=self, warehouse_id=None)
        self._refresh_worker = worker

        def _on_loaded(res: Result):
            if not res.success:
                return
            data = res.data or {}
            with QSignalBlocker(self.cb_item):
                self.cb_item.clear()
                for it in data.get("items", []) or []:
                    self.cb_item.addItem(f"{it.name} ({it.sku})", getattr(it, "id", None))
                self.cb_item.setCurrentIndex(0)

            with QSignalBlocker(self.cb_wh):
                self.cb_wh.clear()
                self.cb_wh.addItem("Tüm", None)
                for wh in data.get("warehouses", []) or []:
                    self.cb_wh.addItem(wh.name, getattr(wh, "id", None))
                self.cb_wh.setCurrentIndex(0)

            self._summary_cache = data.get("balances", []) or []
            self.calculate()
            self._apply_summary_filter()

        def _on_finished():
            if self._refresh_worker is worker:
                self._refresh_worker = None
            self.btn_refresh_summary.setEnabled(True)
            self.btn_refresh_summary.setText(STOCK_MANAGER_REFRESH_TEXT)
            worker.deleteLater()

        worker.result_ready.connect(_on_loaded)
        worker.finished.connect(_on_finished)
        worker.start()

    def calculate(self):
        item_id = self.cb_item.currentData()
        wh_id = self.cb_wh.currentData()
        if not item_id or wh_id is None:
            self.lbl.setText("Stok: -")
            return

        bal = action_get_on_hand(item_id=item_id, warehouse_id=wh_id)
        if bal.success:
            self.lbl.setText(f"Stok: {float(bal.data.get('on_hand', 0) or 0):.3f}")
        else:
            self.lbl.setText("Stok: (hesaplanamadı)")

    def refresh_summary(self):
        self._summary_seq += 1
        seq = self._summary_seq
        worker = self._summary_worker
        if worker is not None and worker.isRunning():
            return
        wh_id = self.cb_wh.currentData()
        self.btn_refresh_summary.setEnabled(False)
        self.btn_refresh_summary.setText("Yukleniyor...")
        worker = SyncWorker(_load_stock_summary_payload, parent=self, warehouse_id=wh_id)
        self._summary_worker = worker

        def _on_summary(res: Result):
            if seq != self._summary_seq:
                return
            if not res.success:
                return
            self._summary_cache = (res.data or {}).get("balances", []) or []
            self._apply_summary_filter()

        def _on_finished():
            if self._summary_worker is worker:
                self._summary_worker = None
            self.btn_refresh_summary.setEnabled(True)
            self.btn_refresh_summary.setText(STOCK_MANAGER_REFRESH_TEXT)
            worker.deleteLater()

        worker.result_ready.connect(_on_summary)
        worker.finished.connect(_on_finished)
        worker.start()

    def _apply_summary_filter(self):
        rows = list(getattr(self, "_summary_cache", []) or [])
        q = (self.le_sum_search.text() or "").strip().lower()
        if q:
            def _hit(r):
                it = r.get("item")
                return q in str(getattr(it, "sku", "") or "").lower() \
                    or q in str(getattr(it, "name", "") or "").lower() \
                    or q in str(getattr(it, "barcode", "") or "").lower() \
                    or q in str(getattr(it, "brand", "") or "").lower() \
                    or q in str(getattr(it, "category", "") or "").lower()
            rows = [r for r in rows if _hit(r)]

        if self.chk_low.isChecked():
            rows = [r for r in rows if r.get("is_low") is True]

        with optimized_table_updates(self.table, len(rows)):
            for i, r in enumerate(rows):
                it = r.get("item")
                _set_row(self.table, i, 0, str(getattr(it, "sku", "") or ""))
                _set_row(self.table, i, 1, str(getattr(it, "name", "") or ""))
                _set_row(self.table, i, 2, _fmt_num(r.get("on_hand", 0.0)))
                _set_row(self.table, i, 3, _fmt_num(r.get("min_stock", 0.0), default=""))
                _set_row(self.table, i, 4, "Kritik" if r.get("is_low") else "OK")
                _set_row(self.table, i, 5, str(getattr(it, "category", "") or ""))















