from . import views as _views

MainInterface = _views.MainInterface
ENABLE_TEST_LAB_UI = _views.DEFAULT_ENABLE_TEST_LAB_UI
_TAB_LOAD_DEBOUNCE_MS = _views._TAB_LOAD_DEBOUNCE_MS

__all__ = ["MainInterface", "ENABLE_TEST_LAB_UI", "_TAB_LOAD_DEBOUNCE_MS"]
