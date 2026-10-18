from __future__ import annotations

from PyQt6.QtGui import QAction


class SupportButton:
    def __init__(self, parent=None):
        self.parent = parent

    def create_action(self):
        action = QAction("☕ Bana bir kahve al", self.parent)
        action.setToolTip("OrderScout'un geliştirilmesine gönüllü destek ol")
        action.setData("support")
        action.triggered.connect(self.open_dialog)
        return action

    def open_dialog(self):
        from .support_dialog import SupportDialog

        SupportDialog(self.parent).exec()
