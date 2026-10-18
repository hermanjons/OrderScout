from PyQt6.QtCore import QObject, pyqtSignal


class OrderSignals(QObject):
    # Emitted when order rows change (insert/update/delete)
    orders_changed = pyqtSignal()

    # Emitted when orders are loaded into UI
    orders_loaded = pyqtSignal(list)  # payload = order list

    # Emitted after DB persistence with payload for downstream workflows
    # payload = {"source": str, "order_item_list": list, "order_data_list": list, "db_result": dict}
    orders_persisted = pyqtSignal(dict)


# Singleton signal bus
order_signals = OrderSignals()
