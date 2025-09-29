from PyQt6.QtCore import QObject, pyqtSignal

class AccountSignals(QObject):
    company_changed = pyqtSignal()

# Global tekil instance
account_signals = AccountSignals()
