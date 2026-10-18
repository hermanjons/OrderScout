from __future__ import annotations

import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QWidget

from settings import ASSETS_DIR
from Testing.constants.ui_constants import (
    TEST_LAB_ACTION_DATA,
    TEST_LAB_ACTION_TEXT,
    TEST_LAB_ACTION_TOOLTIP,
)


class TestLabButton:
    def __init__(self, parent: QWidget | None = None):
        self.parent = parent

    def create_action(self) -> QAction:
        icon_path = os.path.join(ASSETS_DIR, "test-icon.png")
        action = QAction(QIcon(icon_path), TEST_LAB_ACTION_TEXT, self.parent)
        action.setToolTip(TEST_LAB_ACTION_TOOLTIP)
        action.setData(TEST_LAB_ACTION_DATA)
        action.triggered.connect(self.open_dialog)

        if self.parent and hasattr(self.parent, "toolBar"):
            self.parent.toolBar.setIconSize(QSize(32, 32))

        return action

    def open_dialog(self) -> None:
        from .test_lab_dialog import TestLabDialog

        dlg = TestLabDialog(self.parent)
        dlg.setWindowState(dlg.windowState() | Qt.WindowState.WindowMaximized)
        dlg.exec()


def __getattr__(name: str):
    if name == "TestLabDialog":
        from .test_lab_dialog import TestLabDialog

        return TestLabDialog
    raise AttributeError(name)


__all__ = ["TestLabButton", "TestLabDialog"]
