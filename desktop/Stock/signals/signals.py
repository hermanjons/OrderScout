# Stock/signals/signals.py
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class StockSignals(QObject):
    item_created = pyqtSignal(int)
    warehouse_created = pyqtSignal(int)
    tx_created = pyqtSignal(int)
    refreshed = pyqtSignal()
    quick_access_changed = pyqtSignal(str, int)


stock_signals = StockSignals()
