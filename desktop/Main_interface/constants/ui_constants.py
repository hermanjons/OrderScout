from __future__ import annotations

MAIN_WINDOW_TITLE = "OrderScout - Ana Panel"
MAIN_WINDOW_GEOMETRY = (100, 100, 1000, 700)
MAIN_TOOLBAR_TITLE = "Ana Toolbar"
MAIN_TOOLBAR_ICON_SIZE = (40, 40)
MAIN_TOOLBAR_STYLE = """
QToolBar {
    spacing: 10px;
    padding: 5px 8px;
    min-height: 58px;
}
QToolBar QToolButton {
    min-width: 48px;
    min-height: 48px;
    padding: 4px;
}
"""
MAIN_TAB_LABELS = {
    "orders": "Siparişler",
    "stock": "Stok",
    "listing": "İlanlar",
    "marketplaces": "Pazaryerleri",
    "finance": "Finans",
    "logistics": "Lojistik",
    "ai": "AI",
}
MAIN_AI_TAB_ICON_SIZE = (40, 40)
MAIN_TAB_LOADING_TEMPLATE = "{label} hazırlanıyor..."

__all__ = [
    "MAIN_WINDOW_TITLE",
    "MAIN_WINDOW_GEOMETRY",
    "MAIN_TOOLBAR_TITLE",
    "MAIN_TOOLBAR_ICON_SIZE",
    "MAIN_TOOLBAR_STYLE",
    "MAIN_TAB_LABELS",
    "MAIN_AI_TAB_ICON_SIZE",
    "MAIN_TAB_LOADING_TEMPLATE",
]
