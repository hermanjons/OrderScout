from PyQt6.QtCore import QObject, pyqtSignal


class MarketplaceSignals(QObject):
    marketplaces_changed = pyqtSignal()


marketplace_signals = MarketplaceSignals()
