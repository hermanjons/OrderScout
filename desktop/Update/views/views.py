from __future__ import annotations

import os

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QAction, QIcon

from settings import ASSETS_DIR


class UpdateToolbarButton:
    def __init__(self, parent=None, *, trigger_callback=None):
        self.parent = parent
        self.trigger_callback = trigger_callback

    def create_action(self) -> QAction:
        icon_path = os.path.join(ASSETS_DIR, "update-icon.png")
        action = QAction(QIcon(icon_path), "Güncellemeleri Denetle", self.parent)
        action.setToolTip("Yeni sürüm kontrolü yap")
        action.setIconText("Güncelle")
        action.setIconVisibleInMenu(True)
        action.setCheckable(False)

        if self.parent and hasattr(self.parent, "toolBar"):
            self.parent.toolBar.setIconSize(QSize(32, 32))

        if self.trigger_callback:
            action.triggered.connect(self.trigger_callback)
        return action


def __getattr__(name: str):
    if name == "UpdateCenterDialog":
        from .update_center_dialog import UpdateCenterDialog

        return UpdateCenterDialog
    if name == "UpdateProgressDialog":
        from .update_progress_dialog import UpdateProgressDialog

        return UpdateProgressDialog
    raise AttributeError(name)


__all__ = ["UpdateToolbarButton", "UpdateCenterDialog", "UpdateProgressDialog"]
