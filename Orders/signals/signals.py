from PyQt6.QtCore import QObject, pyqtSignal

class OrderSignals(QObject):
    # Siparişlerde ekleme/silme/güncelleme olursa tetiklenecek
    orders_changed = pyqtSignal()

# Global tekil instance
order_signals = OrderSignals()
