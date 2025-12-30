from PyQt6.QtCore import QObject, pyqtSignal


class OrderSignals(QObject):
    # Siparişlerde ekleme/silme/güncelleme olursa tetiklenecek
    orders_changed = pyqtSignal()

    # Siparişler UI'da yüklendiğinde tetiklenecek
    orders_loaded = pyqtSignal(list)  # payload = sipariş listesi


# Global tekil instance
order_signals = OrderSignals()
