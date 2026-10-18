from PyQt6.QtCore import QObject, pyqtSignal


class LogisticsSignals(QObject):
    cargo_providers_changed = pyqtSignal()
    cargo_tariffs_changed = pyqtSignal()


logistics_signals = LogisticsSignals()
