from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QAction, QIcon

from AI.constants.ui_constants import AI_MANAGER_ACTION_DATA, AI_MANAGER_ACTION_TEXT, AI_MANAGER_ACTION_TOOLTIP
from AI.views.ai_manager_dialog import AIManagerDialog, _ai_icon_path


class AIManagerButton:
    def __init__(self, parent=None):
        self.parent = parent
        self._window: Optional[AIManagerDialog] = None

    def create_action(self) -> QAction:
        action = QAction(QIcon(_ai_icon_path()), AI_MANAGER_ACTION_TEXT, self.parent)
        action.setToolTip(AI_MANAGER_ACTION_TOOLTIP)
        action.setIconText(AI_MANAGER_ACTION_TEXT)
        action.setIconVisibleInMenu(True)
        action.setData(AI_MANAGER_ACTION_DATA)
        action.setCheckable(False)

        if self.parent and hasattr(self.parent, "toolBar"):
            self.parent.toolBar.setIconSize(QSize(32, 32))

        action.triggered.connect(self.open_dialog)
        return action

    def open_dialog(self) -> None:
        if self._window is not None and self._window.isVisible():
            if self._window.isMinimized():
                self._window.showNormal()
            self._window.showMaximized()
            self._window.raise_()
            self._window.activateWindow()
            return

        self._window = AIManagerDialog(self.parent)
        self._window.destroyed.connect(lambda *_: setattr(self, "_window", None))
        self._window.show()
        self._window.showMaximized()
        self._window.raise_()
        self._window.activateWindow()


__all__ = [
    "AIManagerButton",
    "AIManagerDialog",
]
