from PyQt6.QtCore import QObject, pyqtSignal


class ListingSignals(QObject):
    # badge count changed (e.g. new listings saved)
    badge_changed = pyqtSignal(int)
    # clear badge / mark as seen
    badge_cleared = pyqtSignal()
    # listing fetch/save lifecycle
    fetch_started = pyqtSignal(object)
    products_loaded = pyqtSignal(object)
    products_save_started = pyqtSignal(object)
    products_saved = pyqtSignal(object)
    products_save_failed = pyqtSignal(object)
    # local listing mutations
    stock_matches_changed = pyqtSignal(object)
    cost_matches_changed = pyqtSignal(object)
    cost_snapshots_synced = pyqtSignal(object)
    listing_cache_updated = pyqtSignal(object)


listing_signals = ListingSignals()
