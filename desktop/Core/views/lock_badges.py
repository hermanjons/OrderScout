from __future__ import annotations

from PyQt6.QtWidgets import QWidget


def _drop_disabled_lock_artifacts(widget: QWidget | None) -> None:
    if widget is None:
        return
    for attr_name in (
        "_disabled_lock_badge",
        "_disabled_lock_popup",
        "_disabled_lock_popup_panel",
        "_disabled_lock_popup_label",
    ):
        artifact = getattr(widget, attr_name, None)
        if artifact is None:
            continue
        try:
            artifact.hide()
        except Exception:
            pass
        try:
            artifact.deleteLater()
        except Exception:
            pass
        try:
            setattr(widget, attr_name, None)
        except Exception:
            pass
    try:
        widget._lock_on_disabled = False
    except Exception:
        pass
    try:
        widget._disabled_lock_reason = ""
    except Exception:
        pass


def _hide_disabled_lock_reason(widget: QWidget) -> None:
    _drop_disabled_lock_artifacts(widget)


def _show_disabled_lock_reason(widget: QWidget) -> None:
    _drop_disabled_lock_artifacts(widget)


def _init_disabled_lock_badge(widget: QWidget, *, tooltip: str = "Bu alan bu kayıtta değiştirilemez.") -> None:
    _ = tooltip
    _drop_disabled_lock_artifacts(widget)


def _position_disabled_lock_badge(widget: QWidget) -> None:
    _drop_disabled_lock_artifacts(widget)


def _set_lock_on_disabled(widget: QWidget, enabled: bool) -> None:
    _ = enabled
    _drop_disabled_lock_artifacts(widget)


def _lock_on_disabled(widget: QWidget) -> bool:
    _drop_disabled_lock_artifacts(widget)
    return False


def _sync_disabled_lock_badge(widget: QWidget) -> None:
    _drop_disabled_lock_artifacts(widget)
