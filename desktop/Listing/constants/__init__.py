"""Listing constants package."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_MODULES = {
    "LISTING_BUILTIN_RULE_HANDLERS": ".cost_rules",
    "LISTING_DEFAULT_FETCH_PAGE_SIZE": ".fetch_constants",
    "LISTING_STAGE_FETCH_PAGE_SIZE": ".fetch_constants",
    "canonical_platform_code": ".platform_constants",
    "platform_label_for_code": ".platform_constants",
}

__all__ = sorted({*_EXPORT_MODULES, "ui_text"})


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


def ui_text(path: str, default: Any = "") -> Any:
    return default
