from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QAction, QIcon

try:
    from Account.constants.toolbar_constants import (
        ACCOUNT_TOOLBAR_ACTION_KEY,
        ACCOUNT_TOOLBAR_ACTION_TEXT,
        ACCOUNT_TOOLBAR_ACTION_TOOLTIP,
        ACCOUNT_TOOLBAR_ICON_SIZE,
    )
    from Account.constants.paths import ACCOUNT_TOOLBAR_ICON_PATH
except ModuleNotFoundError:
    desktop_root = Path(__file__).resolve().parents[2]
    desktop_root_str = str(desktop_root)
    if desktop_root_str not in sys.path:
        sys.path.insert(0, desktop_root_str)
    from Account.constants.toolbar_constants import (
        ACCOUNT_TOOLBAR_ACTION_KEY,
        ACCOUNT_TOOLBAR_ACTION_TEXT,
        ACCOUNT_TOOLBAR_ACTION_TOOLTIP,
        ACCOUNT_TOOLBAR_ICON_SIZE,
    )
    from Account.constants.paths import ACCOUNT_TOOLBAR_ICON_PATH

if TYPE_CHECKING:
    from Account.views.company_manager_dialog import CompanyManagerDialog


class CompanyManagerButton:
    def __init__(self, parent=None):
        self.parent = parent

    def create_action(self):
        action = QAction(QIcon(str(ACCOUNT_TOOLBAR_ICON_PATH)), ACCOUNT_TOOLBAR_ACTION_TEXT, self.parent)
        action.setToolTip(ACCOUNT_TOOLBAR_ACTION_TOOLTIP)
        action.setIconText(ACCOUNT_TOOLBAR_ACTION_TEXT)
        action.setIconVisibleInMenu(True)
        action.setData(ACCOUNT_TOOLBAR_ACTION_KEY)
        action.setEnabled(True)
        action.setCheckable(False)

        if self.parent and hasattr(self.parent, "toolBar"):
            self.parent.toolBar.setIconSize(QSize(*ACCOUNT_TOOLBAR_ICON_SIZE))

        action.triggered.connect(self.open_comp_manage_dialog)
        return action

    def open_comp_manage_dialog(self):
        from Account.views.company_manager_dialog import CompanyManagerDialog

        dialog = CompanyManagerDialog(self.parent)
        dialog.exec()


def __getattr__(name: str):
    if name != "CompanyManagerDialog":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from Account.views.company_manager_dialog import CompanyManagerDialog

    globals()[name] = CompanyManagerDialog
    return CompanyManagerDialog


__all__ = [
    "CompanyManagerButton",
    "CompanyManagerDialog",
]
