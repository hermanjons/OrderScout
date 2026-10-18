from __future__ import annotations


def __getattr__(name: str):
    if name == "LabelPrintManagerWindow":
        from .label_print_manager_window import LabelPrintManagerWindow

        return LabelPrintManagerWindow
    raise AttributeError(name)


__all__ = ["LabelPrintManagerWindow"]
