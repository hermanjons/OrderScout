from typing import Any

from .ui_constants import (
    MAIN_AI_TAB_ICON_SIZE,
    MAIN_TAB_LABELS,
    MAIN_TAB_LOADING_TEMPLATE,
    MAIN_TOOLBAR_ICON_SIZE,
    MAIN_TOOLBAR_STYLE,
    MAIN_TOOLBAR_TITLE,
    MAIN_WINDOW_GEOMETRY,
    MAIN_WINDOW_TITLE,
)

__all__ = [
    "MAIN_AI_TAB_ICON_SIZE",
    "MAIN_TAB_LABELS",
    "MAIN_TAB_LOADING_TEMPLATE",
    "MAIN_TOOLBAR_ICON_SIZE",
    "MAIN_TOOLBAR_STYLE",
    "MAIN_TOOLBAR_TITLE",
    "MAIN_WINDOW_GEOMETRY",
    "MAIN_WINDOW_TITLE",
]


def ui_text(path: str, default: Any = "") -> Any:
    return default


__all__.append("ui_text")
