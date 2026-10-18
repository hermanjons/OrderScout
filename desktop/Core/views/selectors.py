from __future__ import annotations

import math
import os

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QAbstractButton,
    QLabel, QHBoxLayout, QSizePolicy, QGraphicsDropShadowEffect,
    QLineEdit, QToolButton, QLayout, QTableWidget, QHeaderView,
    QListView, QListWidget, QListWidgetItem, QAbstractItemView, QFrame,
    QDateEdit, QCalendarWidget, QComboBox, QGraphicsOpacityEffect, QDialog,
    QAbstractScrollArea, QGraphicsBlurEffect,
    QFileDialog, QScrollArea, QMessageBox
    , QCheckBox, QSplitter, QSplitterHandle
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QPoint, QPropertyAnimation, QEasingCurve, pyqtProperty, pyqtSignal, \
    QAbstractAnimation, QSize, QRect, QEvent, QDate, QTime, QUrl, QRegularExpression, QSignalBlocker
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase, QPixmap, QPalette, QDoubleValidator, QConicalGradient, QFontMetrics, QBrush, QKeyEvent, QCursor, QPainterPath, QGuiApplication, QTextCharFormat, QRadialGradient, QDesktopServices, QRegularExpressionValidator, QValidator, QIcon
from Core.constants.ui_constants import (
    DATE_SELECTOR_ICON_TEXT,
    DATE_SELECTOR_MONTH_NAMES,
    DATE_SELECTOR_NEXT_MONTH_TEXT,
    DATE_SELECTOR_PREV_MONTH_TEXT,
    DATE_SELECTOR_RANGE_END_HINT_TEXT,
    DATE_SELECTOR_RANGE_END_TEXT,
    DATE_SELECTOR_RANGE_SELECTED_HINT_TEXT,
    DATE_SELECTOR_RANGE_SEPARATOR_TEXT,
    DATE_SELECTOR_RANGE_START_HINT_TEXT,
    SWITCH_SELECT_ARROW_CLOSED_TEXT,
    SWITCH_SELECT_ARROW_OPEN_TEXT,
    SWITCH_SELECT_SEARCH_PLACEHOLDER,
    TIME_SELECTOR_END_LABEL,
    TIME_SELECTOR_ICON_TEXT,
    TIME_SELECTOR_NOW_TEXT,
    TIME_SELECTOR_OK_TEXT,
    TIME_SELECTOR_RANGE_HINT_TEXT,
    TIME_SELECTOR_RANGE_SEPARATOR_TEXT,
    TIME_SELECTOR_SINGLE_HINT_TEXT,
    TIME_SELECTOR_START_LABEL,
)
from Feedback.processors.pipeline import Result, map_error_to_message


# ========================
# Rounded path helper

from .controls import SwitchButton
from .lock_badges import _init_disabled_lock_badge, _lock_on_disabled, _position_disabled_lock_badge, _set_lock_on_disabled, _sync_disabled_lock_badge

class _ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _SwitchSelectItem(QWidget):
    toggled = pyqtSignal(str, bool)

    def __init__(self, text: str, checked: bool = False, parent=None):
        super().__init__(parent)
        self._text = text or ""
        self.setObjectName("SwitchSelectItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        self._label = QLabel(self._text)
        self._label.setObjectName("SwitchSelectItemLabel")

        self._switch = SwitchButton()
        self._switch.setChecked(bool(checked))
        self._switch.clicked.connect(self._on_switch_clicked)

        layout.addWidget(self._label, 1)
        layout.addWidget(
            self._switch,
            0,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

    def text(self) -> str:
        return self._text

    def isChecked(self) -> bool:
        return self._switch.isChecked()

    def setChecked(self, checked: bool) -> None:
        with QSignalBlocker(self._switch):
            self._switch.setChecked(bool(checked))

    def mousePressEvent(self, event):
        if self._switch.geometry().contains(event.pos()):
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._switch.click()
            try:
                self._switch._animate()
            except Exception:
                pass
        super().mousePressEvent(event)

    def _on_switch_clicked(self, checked: bool) -> None:
        self.toggled.emit(self._text, bool(checked))


class SwitchSelectWidget(QWidget):
    """
    Dropdown-like select panel with search + switch items.
    - Popup overlay: list covers content below (no push-down).
    - Multi-select by default; switches show selection.
    """

    selectionChanged = pyqtSignal(list)
    currentIndexChanged = pyqtSignal(int)

    def __init__(
            self,
            parent=None,
            *,
            title: str = "",
            all_text: str = "Tümü",
            empty_text: str = "Seçiniz",
            multi: bool = True,
            search_enabled: bool = True,
            include_all: bool | None = None,
            default_all: bool | None = None,
            allow_empty: bool = False,
            all_data=None
    ):
        super().__init__(parent)
        self._title = title or ""
        self._all_text = all_text or "Tümü"
        self._empty_text = empty_text or "Seçiniz"
        self._multi = bool(multi)
        self._search_enabled = bool(search_enabled)
        if include_all is None:
            self._include_all = bool(self._title) and self._all_text.strip().casefold() in {"tümü", "tüm", "all"}
        else:
            self._include_all = bool(include_all)
        if default_all is None:
            self._default_all = bool(self._include_all)
        else:
            self._default_all = bool(default_all)
        if not self._include_all:
            self._default_all = False
        self._allow_empty = bool(allow_empty)
        self._all_data = all_data if all_data is not None else "all"
        self._panel_open = False
        self._suppress_toggle = False
        self._syncing = False
        self._items = []
        self._item_map = {}
        self._last_visible_count = 0
        self._search = None
        self._screen_margin = 24
        self._batch_update_depth = 0
        self._deferred_apply_all_rules = False

        self._list_max_items = 8
        self._list_min_height = 44

        self._header = _ClickableFrame(self)
        self._header.setObjectName("SwitchSelectHeader")
        self._header.setProperty("open", False)
        self._header.clicked.connect(self._on_header_clicked)

        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(8)

        self._summary = QLabel(self._header)
        self._summary.setObjectName("SwitchSelectSummary")
        self._summary.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._summary.setWordWrap(False)
        self._summary.setMinimumWidth(0)
        # Prevent long selected text from forcing parent layouts to resize.
        self._summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self._arrow = QToolButton(self._header)
        self._arrow.setObjectName("SwitchSelectArrow")
        self._arrow.setText(SWITCH_SELECT_ARROW_CLOSED_TEXT)
        self._arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._arrow.clicked.connect(self._on_header_clicked)

        header_layout.addWidget(self._summary, 1)
        header_layout.addWidget(
            self._arrow,
            0,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self._popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._popup.setObjectName("SwitchSelectPopup")
        self._popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._popup.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._popup.setMouseTracking(True)
        self._popup.installEventFilter(self)
        panel_layout = QVBoxLayout(self._popup)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.setSpacing(6)

        self._search = QLineEdit(self._popup)
        self._search.setObjectName("SwitchSelectSearch")
        self._search.setPlaceholderText(SWITCH_SELECT_SEARCH_PLACEHOLDER)
        self._search.setClearButtonEnabled(True)
        self._search.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._search.setMouseTracking(True)
        self._search.setCursor(Qt.CursorShape.IBeamCursor)
        self._search.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._search.textEdited.connect(self._on_search_text)
        self._search.installEventFilter(self)

        self._search_glow = QGraphicsDropShadowEffect(self._search)
        self._search_glow.setBlurRadius(0)
        self._search_glow.setOffset(0, 0)
        self._search_glow.setColor(QColor(0, 0, 0, 0))
        self._search.setGraphicsEffect(self._search_glow)

        self._popup.setFocusProxy(self._search)

        self._list = QListWidget(self._popup)
        self._list.setObjectName("SwitchSelectList")
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setUniformItemSizes(True)
        self._list.setSpacing(2)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setMouseTracking(True)

        self._deferred_refresh_timer = QTimer(self)
        self._deferred_refresh_timer.setSingleShot(True)
        self._deferred_refresh_timer.setInterval(0)
        self._deferred_refresh_timer.timeout.connect(self._run_deferred_refresh)

        if self._search_enabled:
            panel_layout.addWidget(self._search)
        else:
            self._search.setVisible(False)
        panel_layout.addWidget(self._list)

        self._popup.setVisible(False)
        _init_disabled_lock_badge(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._header)

        self._apply_style()
        self._update_summary()
        self._update_search_visual()
        if self._include_all:
            self.addItem(self._all_text, data=self._all_data, checked=self._default_all)
            self._apply_all_rules(changed_text=self._all_text, changed_checked=self._default_all)

    # --------------------------
    # Public API
    # --------------------------
    def setTitle(self, text: str) -> None:
        self._title = text or ""
        self._update_summary()

    def setAllText(self, text: str) -> None:
        self._all_text = text or "Tümü"
        self._update_summary()

    def setEmptyText(self, text: str) -> None:
        self._empty_text = text or "Seçiniz"
        self._update_summary()

    def setPlaceholderText(self, text: str) -> None:
        if self._search is not None:
            self._search.setPlaceholderText(text or "")

    def setMultiSelect(self, enabled: bool) -> None:
        self._multi = bool(enabled)
        if not self._multi and len(self.selectedTexts()) > 1:
            keep = self.selectedTexts()[:1]
            self.setSelectedTexts(keep)

    def setSearchEnabled(self, enabled: bool) -> None:
        self._search_enabled = bool(enabled)
        self._search.setVisible(self._search_enabled)
        self._update_list_height()
        self._update_search_visual()

    def addItem(self, text: str, data=None, checked: bool = False) -> None:
        text = (text or "").strip()
        if not text or text in self._item_map:
            return

        widget = _SwitchSelectItem(text, checked=checked)
        widget.toggled.connect(self._on_item_toggled)

        item = QListWidgetItem()
        hint = widget.sizeHint()
        # Let QListWidget control row width from viewport width, not from long text.
        if hint.width() > 0:
            hint.setWidth(0)
        item.setSizeHint(hint)
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

        entry = {
            "text": text,
            "search_text": text.casefold(),
            "data": data,
            "checked": bool(checked),
            "item": item,
            "widget": widget,
            "force_hidden": False,
        }
        self._items.append(entry)
        self._item_map[text] = entry

        if checked:
            self._syncing = True
            if not self._multi:
                for other in self._items:
                    if other is not entry and other["checked"]:
                        other["checked"] = False
                        other["widget"].setChecked(False)
            self._syncing = False

        needs_all_rules = self._include_all and text != self._all_text
        if self._batch_update_depth > 0:
            self._deferred_apply_all_rules = self._deferred_apply_all_rules or needs_all_rules
            return
        if self._should_defer_refresh():
            self._deferred_apply_all_rules = self._deferred_apply_all_rules or needs_all_rules
            self._schedule_deferred_refresh()
            return
        if needs_all_rules:
            self._apply_all_rules(changed_text=text, changed_checked=checked)
        self._apply_filter()
        self._update_summary()

    def addItems(self, items: list) -> None:
        values = list(items or [])
        if not values:
            return
        self._batch_update_depth += 1
        self._list.setUpdatesEnabled(False)
        try:
            for item in values:
                if isinstance(item, (list, tuple)) and len(item) >= 1:
                    text = item[0]
                    data = item[1] if len(item) > 1 else None
                    checked = bool(item[2]) if len(item) > 2 else False
                    self.addItem(text, data=data, checked=checked)
                else:
                    self.addItem(str(item))
        finally:
            self._batch_update_depth = max(0, self._batch_update_depth - 1)
            self._list.setUpdatesEnabled(True)
        if self._include_all or self._deferred_apply_all_rules:
            self._apply_all_rules()
            self._deferred_apply_all_rules = False
        self._apply_filter()
        self._update_summary()

    def clear(self) -> None:
        self._items = []
        self._item_map = {}
        self._list.clear()
        if self._include_all:
            self.addItem(self._all_text, data=self._all_data, checked=self._default_all)
            self._apply_all_rules(changed_text=self._all_text, changed_checked=self._default_all)
        self._update_summary()

    def setSelectedTexts(self, texts: list[str]) -> None:
        desired = [t for t in (texts or []) if t in self._item_map]
        if not self._multi and len(desired) > 1:
            desired = desired[:1]

        desired_set = set(desired)
        self._syncing = True
        for entry in self._items:
            checked = entry["text"] in desired_set
            entry["checked"] = checked
            entry["widget"].setChecked(checked)
        self._syncing = False

        if self._include_all:
            self._apply_all_rules()
        self._update_summary()
        self._emit_selection_changed()


    def selectedTexts(self) -> list[str]:
        return [e["text"] for e in self._items if e["checked"]]

    def selectedData(self) -> list:
        return [e["data"] for e in self._items if e["checked"]]

    def currentIndex(self) -> int:
        for i, entry in enumerate(self._items):
            if entry["checked"]:
                return i
        return -1

    def currentText(self) -> str:
        selected = self.selectedTexts()
        return selected[0] if selected else ""

    def currentData(self):
        selected = self.selectedData()
        return selected[0] if selected else None

    def setCurrentIndex(self, index: int) -> None:
        if index is None or index < 0 or index >= len(self._items):
            self.setSelectedTexts([])
            return
        self.setSelectedTexts([self._items[index]["text"]])

    def setCurrentText(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            self.setSelectedTexts([])
            return
        if text not in self._item_map:
            self.addItem(text)
        self.setSelectedTexts([text])

    def setItemEnabled(self, text: str, enabled: bool) -> None:
        entry = self._item_map.get(text)
        if entry is None:
            return
        try:
            entry["widget"].setEnabled(bool(enabled))
        except Exception:
            pass

    def findText(self, text: str) -> int:
        for i, entry in enumerate(self._items):
            if entry["text"] == text:
                return i
        return -1

    def findData(self, data) -> int:
        for i, entry in enumerate(self._items):
            if entry["data"] == data:
                return i
        return -1

    def setEditable(self, _editable: bool) -> None:
        return

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self._header.setEnabled(enabled)
        self._arrow.setEnabled(enabled)
        self._summary.setEnabled(enabled)
        if not enabled:
            self.setPanelOpen(False)
        _sync_disabled_lock_badge(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        _position_disabled_lock_badge(self)
        self._sync_summary_tooltip()

    def setLockOnDisabled(self, enabled: bool) -> None:
        _set_lock_on_disabled(self, enabled)

    def lockOnDisabled(self) -> bool:
        return _lock_on_disabled(self)

    def setSizeAdjustPolicy(self, *_args, **_kwargs) -> None:
        return

    def togglePanel(self) -> None:
        if self._suppress_toggle:
            return
        self.setPanelOpen(not self._panel_open)

    def _on_header_clicked(self) -> None:
        if self._suppress_toggle:
            return
        if self._panel_open or (self._popup and self._popup.isVisible()):
            self._block_toggle()
            self.setPanelOpen(False)
            return
        self.setPanelOpen(True)

    def setPanelOpen(self, open_state: bool) -> None:
        self._panel_open = bool(open_state)
        self._header.setProperty("open", self._panel_open)
        self._header.style().unpolish(self._header)
        self._header.style().polish(self._header)
        self._arrow.setText(SWITCH_SELECT_ARROW_OPEN_TEXT if self._panel_open else SWITCH_SELECT_ARROW_CLOSED_TEXT)

        if self._panel_open:
            self._open_popup()
        else:
            self._close_popup()

    # --------------------------
    # Internal
    # --------------------------
    def _open_popup(self) -> None:
        self._run_deferred_refresh()
        self._apply_filter()
        self._update_list_height()
        self._position_popup()
        self._popup.show()
        self._popup.raise_()
        self._popup.activateWindow()
        self._sync_cursor_from_global()
        if self._search_enabled:
            self._force_search_focus(select_all=True)
            QTimer.singleShot(20, lambda: self._force_search_focus(select_all=False))
            QTimer.singleShot(20, self._sync_cursor_from_global)
        self._update_search_visual()

    def _close_popup(self) -> None:
        if self._popup.isVisible():
            self._popup.hide()
        with QSignalBlocker(self._search):
            self._search.clear()
        self._apply_filter()
        self._update_search_visual()

    def _position_popup(self) -> None:
        if not self._popup:
            return
        self._popup.adjustSize()
        header_w = int(self._header.width())
        hint_w = int(self._popup.sizeHint().width())
        list_col_w = int(self._list.sizeHintForColumn(0))
        if list_col_w < 0:
            list_col_w = 0
        scroll_w = 0
        try:
            scroll = self._list.verticalScrollBar()
            if scroll is not None:
                scroll_w = int(scroll.sizeHint().width())
        except Exception:
            scroll_w = 0
        search_w = int(self._search.sizeHint().width()) if (self._search_enabled and self._search is not None) else 0
        content_w = list_col_w + scroll_w + 44
        width = max(header_w, hint_w, search_w, content_w, 240)
        self._popup.setFixedWidth(int(width))
        popup_h = self._popup.sizeHint().height()
        anchor = self._header.mapToGlobal(self._header.rect().bottomLeft())
        x = anchor.x()
        y = anchor.y() + 6

        screen = QGuiApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            margin = int(getattr(self, "_screen_margin", 24))
            right_limit = geo.right() - margin
            left_limit = geo.left() + margin
            bottom_limit = geo.bottom() - margin
            top_limit = geo.top() + margin

            if x + width > right_limit:
                x = max(left_limit, right_limit - width + 1)
            if x < left_limit:
                x = left_limit
            if y + popup_h > bottom_limit:
                anchor_top = self._header.mapToGlobal(self._header.rect().topLeft())
                y = anchor_top.y() - popup_h - 6
            if y < top_limit:
                y = top_limit
            if y + popup_h > bottom_limit:
                y = max(top_limit, bottom_limit - popup_h + 1)

        self._popup.move(int(x), int(y))

    def _apply_cursor_for_pos(self, pos: QPoint) -> None:
        if not self._search_enabled or self._search is None:
            self._popup.unsetCursor()
            return
        if self._search.geometry().contains(pos):
            self._popup.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self._popup.unsetCursor()

    def _sync_cursor_from_global(self) -> None:
        if not self._popup or not self._popup.isVisible():
            return
        global_pos = QCursor.pos()
        local = self._popup.mapFromGlobal(global_pos)
        self._apply_cursor_for_pos(local)

    def eventFilter(self, source, event):
        if self._search is not None and source is self._search:
            if event.type() == QEvent.Type.MouseButtonPress:
                self._force_search_focus(select_all=False)
                self._update_search_visual()
            if event.type() == QEvent.Type.Enter:
                self._popup.setCursor(Qt.CursorShape.IBeamCursor)
            if event.type() == QEvent.Type.KeyPress:
                self._update_search_visual()
            if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
                self._update_search_visual()
            if event.type() == QEvent.Type.Leave:
                self._popup.unsetCursor()
        if source is self._popup and event.type() == QEvent.Type.MouseButtonPress:
            try:
                pos = event.position().toPoint()
            except Exception:
                pos = event.pos()
            self._popup.activateWindow()
            if self._search_enabled and self._search.geometry().contains(pos):
                self._force_search_focus(select_all=False)
                self._update_search_visual()
        if source is self._popup and event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove, QEvent.Type.Enter):
            try:
                pos = event.position().toPoint()
            except Exception:
                pos = event.pos()
            self._apply_cursor_for_pos(pos)
        if source is self._popup and event.type() == QEvent.Type.Hide:
            if self._panel_open:
                self._panel_open = False
                self._block_toggle()
                self._header.setProperty("open", False)
                self._header.style().unpolish(self._header)
                self._header.style().polish(self._header)
                self._arrow.setText(SWITCH_SELECT_ARROW_CLOSED_TEXT)
                with QSignalBlocker(self._search):
                    self._search.clear()
                self._apply_filter()
                self._update_search_visual()
        return super().eventFilter(source, event)

    def _block_toggle(self, ms: int = 180) -> None:
        self._suppress_toggle = True
        QTimer.singleShot(ms, self._clear_block_toggle)

    def _clear_block_toggle(self) -> None:
        self._suppress_toggle = False

    def _should_defer_refresh(self) -> bool:
        return not self._panel_open and not self.isVisible()

    def _schedule_deferred_refresh(self) -> None:
        if not self._deferred_refresh_timer.isActive():
            self._deferred_refresh_timer.start()

    def _run_deferred_refresh(self) -> None:
        if self._deferred_refresh_timer.isActive():
            self._deferred_refresh_timer.stop()
        if self._deferred_apply_all_rules:
            self._apply_all_rules()
            self._deferred_apply_all_rules = False
        self._apply_filter()
        self._update_summary()

    def _force_search_focus(self, *, select_all: bool = False) -> None:
        if not self._search_enabled or self._search is None:
            return
        try:
            self._popup.activateWindow()
        except Exception:
            pass
        self._search.setFocus(Qt.FocusReason.MouseFocusReason)
        if select_all:
            self._search.selectAll()
        else:
            try:
                self._search.setCursorPosition(len(self._search.text()))
            except Exception:
                pass

    def _apply_style(self) -> None:
        style = """
            QFrame#SwitchSelectHeader {
                background: #ffffff;
                border: 1px solid #dbe3ee;
                border-radius: 12px;
            }
            QFrame#SwitchSelectHeader[open="true"] {
                border-color: #60a5fa;
                background: #f8fbff;
            }
            QLabel#SwitchSelectSummary {
                color: #0b1324;
                font-weight: 600;
            }
            QToolButton#SwitchSelectArrow {
                border: none;
                min-width: 28px;
                min-height: 28px;
                color: #667085;
            }
            QToolButton#SwitchSelectArrow:hover {
                color: #0f172a;
            }
            QFrame#SwitchSelectPopup {
                background: #ffffff;
                border: 1px solid #e6ecf2;
                border-radius: 12px;
            }
            QLineEdit#SwitchSelectSearch {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                padding: 6px 10px;
                min-height: 30px;
                color: #0b1324;
            }
            QLineEdit#SwitchSelectSearch[state="focus"] {
                border: 1px solid #60a5fa;
            }
            QLineEdit#SwitchSelectSearch[state="typing"] {
                border: 1px solid #22c55e;
            }
            QLineEdit#SwitchSelectSearch[state="error"] {
                border: 1px solid #ef4444;
            }
            QLineEdit#SwitchSelectSearch::placeholder {
                color: #94a3b8;
            }
            QListWidget#SwitchSelectList {
                background: #ffffff;
                border: 1px solid #e6ecf2;
                border-radius: 10px;
                padding: 6px;
                outline: none;
            }
            QWidget#SwitchSelectItem {
                background: #ffffff;
                border-radius: 8px;
            }
            QWidget#SwitchSelectItem:hover {
                background: #f8fafc;
            }
            QLabel#SwitchSelectItemLabel {
                color: #0b1324;
                font-weight: 600;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 6px 2px 6px 2px;
            }
            QScrollBar::handle:vertical {
                background: #cbd5e1;
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
            """
        self.setStyleSheet(style)
        if self._popup:
            self._popup.setStyleSheet(style)

    def _update_summary(self) -> None:
        selected = self.selectedTexts()
        if len(selected) == 0:
            value = self._empty_text
        elif len(selected) == 1:
            value = selected[0]
        else:
            value = f"{len(selected)} seçili"

        if self._title:
            self._summary.setText(f"{self._title}: {value}")
        else:
            self._summary.setText(value)
        self._sync_summary_tooltip()

    def _sync_summary_tooltip(self) -> None:
        summary_label = getattr(self, "_summary", None)
        if summary_label is None:
            return
        text = str(summary_label.text() or "").strip()
        if not text:
            summary_label.setToolTip("")
            return
        width = max(0, int(summary_label.contentsRect().width() or summary_label.width() or 0))
        if width <= 0:
            summary_label.setToolTip("")
            return
        elided = summary_label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(0, width - 2))
        summary_label.setToolTip(text if elided != text else "")

    def _on_item_toggled(self, text: str, checked: bool) -> None:
        if self._syncing:
            return
        entry = self._item_map.get(text)
        if entry is None:
            return

        if checked and not self._multi:
            self._syncing = True
            for other in self._items:
                if other is not entry and other["checked"]:
                    other["checked"] = False
                    other["widget"].setChecked(False)
            self._syncing = False

        entry["checked"] = bool(checked)
        if self._include_all:
            self._apply_all_rules(changed_text=text, changed_checked=checked)
        self._update_summary()
        self._emit_selection_changed()

        if not self._multi and bool(checked):
            # Behave like a native combo box in single-select mode.
            self._block_toggle()
            self.setPanelOpen(False)

    def _emit_selection_changed(self) -> None:
        self.selectionChanged.emit(self.selectedTexts())
        self.currentIndexChanged.emit(self.currentIndex())

    def _on_search_text(self, _text: str) -> None:
        self._apply_filter()
        self._update_search_visual()

    def _apply_filter(self) -> None:
        query = (self._search.text() or "").strip().casefold()
        visible = 0
        for entry in self._items:
            text = entry.get("search_text") or str(entry["text"]).casefold()
            force_hidden = bool(entry.get("force_hidden"))
            hide = force_hidden or (bool(query) and query not in text)
            entry["item"].setHidden(hide)
            if not hide:
                visible += 1
        self._last_visible_count = visible
        self._update_list_height(visible_count=visible)
        self._update_search_visual()

    def _apply_all_rules(self, *, changed_text: str | None = None, changed_checked: bool | None = None) -> None:
        if not self._include_all:
            return
        all_entry = self._item_map.get(self._all_text)
        has_non_all = any(e["text"] != self._all_text for e in self._items)
        if all_entry is not None:
            all_entry["force_hidden"] = not has_non_all
            if not has_non_all:
                self._syncing = True
                all_entry["checked"] = False
                all_entry["widget"].setChecked(False)
                self._syncing = False
                self.setItemEnabled(self._all_text, False)
                return

        selected = [e for e in self._items if e["checked"]]
        selected_texts = [e["text"] for e in selected]

        if not selected_texts:
            if self._allow_empty:
                self.setItemEnabled(self._all_text, True)
                return
            self._syncing = True
            for entry in self._items:
                checked = entry["text"] == self._all_text
                entry["checked"] = checked
                entry["widget"].setChecked(checked)
            self._syncing = False
            self.setItemEnabled(self._all_text, False)
            return

        if self._all_text in selected_texts and len(selected_texts) > 1:
            self._syncing = True
            if changed_text == self._all_text and changed_checked:
                for entry in self._items:
                    if entry["text"] != self._all_text and entry["checked"]:
                        entry["checked"] = False
                        entry["widget"].setChecked(False)
            else:
                entry = self._item_map.get(self._all_text)
                if entry and entry["checked"]:
                    entry["checked"] = False
                    entry["widget"].setChecked(False)
            self._syncing = False

        selected = [e for e in self._items if e["checked"]]
        selected_texts = [e["text"] for e in selected]
        lock_all = (
            not self._allow_empty
            and len(selected_texts) == 1
            and selected_texts[0] == self._all_text
        )
        self.setItemEnabled(self._all_text, not lock_all)

    def _update_list_height(self, *, visible_count: int | None = None) -> None:
        visible = (
            int(visible_count)
            if visible_count is not None
            else sum(1 for e in self._items if not e["item"].isHidden())
        )
        if visible <= 0:
            visible = 1

        item_h = self._list.sizeHintForRow(0)
        if item_h <= 0 and self._items:
            item_h = self._items[0]["widget"].sizeHint().height()
        if item_h <= 0:
            item_h = 32

        max_items = min(visible, self._list_max_items)
        spacing = self._list.spacing()
        target = (item_h * max_items) + (spacing * max(0, max_items - 1)) + 12
        target = max(self._list_min_height, target)
        self._list.setFixedHeight(int(target))
        if self._panel_open:
            self._position_popup()

    def _update_search_visual(self) -> None:
        if not self._search:
            return
        text = (self._search.text() or "").strip()
        has_text = bool(text)
        has_focus = self._search.hasFocus()

        if has_text and self._last_visible_count == 0:
            state = "error"
            glow_color = QColor("#ef4444")
            glow_alpha = 220
            blur = 26
        elif has_text:
            state = "typing"
            t = min(len(text) / 12.0, 1.0)
            glow_color = QColor("#22c55e").lighter(100 + int(30 * t))
            glow_alpha = 120 + int(90 * t)
            blur = 14 + int(12 * t)
        elif has_focus:
            state = "focus"
            glow_color = QColor("#60a5fa")
            glow_alpha = 160
            blur = 18
        else:
            state = "idle"
            glow_color = QColor(0, 0, 0)
            glow_alpha = 0
            blur = 0

        self._search.setProperty("state", state)
        self._search.style().unpolish(self._search)
        self._search.style().polish(self._search)
        self._search.update()

        if self._search_glow:
            glow_color.setAlpha(glow_alpha)
            self._search_glow.setBlurRadius(blur)
            self._search_glow.setColor(glow_color)


# ========================
# 📅 DateSelector
# ========================
class DateSelector(QWidget):
    dateChanged = pyqtSignal(QDate)
    rangeChanged = pyqtSignal(QDate, QDate)

    def __init__(
            self,
            parent=None,
            *,
            display_format: str = "dd.MM.yyyy",
            range_enabled: bool = False,
            placeholder: str = "Tarih seç"
    ):
        super().__init__(parent)
        self._suppress = False
        self._display_format = display_format
        self._range_enabled = bool(range_enabled)
        self._placeholder = placeholder
        self._start: QDate | None = None
        self._end: QDate | None = None
        self._formatted_dates: list[QDate] = []
        self._dimmed_dates: list[QDate] = []
        self._month_hidden_dates: list[QDate] = []
        self._hover_date: QDate | None = None
        self._status = "neutral"

        self._card = QFrame()
        self._card.setObjectName("DateSelectCard")
        self._card.setProperty("focus", False)
        self._card.setCursor(Qt.CursorShape.PointingHandCursor)

        card_layout = QHBoxLayout(self._card)
        card_layout.setContentsMargins(10, 6, 10, 6)
        card_layout.setSpacing(8)

        self._value_wrap = QWidget()
        self._value_wrap.setObjectName("DateSelectValue")
        value_layout = QHBoxLayout(self._value_wrap)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(6)

        self._placeholder_label = QLabel()
        self._placeholder_label.setObjectName("DateSelectPlaceholder")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        self._badge_container = QWidget()
        self._badge_layout = QHBoxLayout(self._badge_container)
        self._badge_layout.setContentsMargins(0, 0, 0, 0)
        self._badge_layout.setSpacing(6)

        self._badge_start = QLabel()
        self._badge_start.setObjectName("DateSelectBadge")
        self._badge_start.setProperty("state", "neutral")
        self._badge_sep = QLabel(DATE_SELECTOR_RANGE_SEPARATOR_TEXT)
        self._badge_sep.setObjectName("DateSelectSeparator")
        self._badge_end = QLabel()
        self._badge_end.setObjectName("DateSelectBadge")
        self._badge_end.setProperty("state", "neutral")
        self._badge_ghost = QLabel(DATE_SELECTOR_RANGE_END_TEXT)
        self._badge_ghost.setObjectName("DateSelectBadgeGhost")
        self._badge_ghost.setProperty("state", "neutral")
        self._badge_single = QLabel()
        self._badge_single.setObjectName("DateSelectBadge")
        self._badge_single.setProperty("state", "neutral")

        self._pulse_effect = QGraphicsOpacityEffect(self._badge_ghost)
        self._badge_ghost.setGraphicsEffect(self._pulse_effect)
        self._pulse_anim = QPropertyAnimation(self._pulse_effect, b"opacity", self)
        self._pulse_anim.setDuration(900)
        self._pulse_anim.setStartValue(0.45)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.stop()

        for w in (self._badge_start, self._badge_sep, self._badge_end, self._badge_ghost, self._badge_single):
            self._badge_layout.addWidget(w)

        self._badge_container.setVisible(False)
        value_layout.addWidget(self._placeholder_label)
        value_layout.addWidget(self._badge_container)

        self._icon = QToolButton()
        self._icon.setObjectName("DateSelectIcon")
        self._icon.setText(DATE_SELECTOR_ICON_TEXT)
        self._icon.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon.clicked.connect(self.toggle_popup)

        card_layout.addWidget(self._value_wrap, 1)
        card_layout.addWidget(self._icon, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._card)

        self._calendar = QCalendarWidget()
        self._calendar.setGridVisible(True)
        self._calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self._calendar.setMinimumWidth(300)
        self._calendar.setNavigationBarVisible(False)
        self._calendar.setMouseTracking(True)
        self._calendar.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._calendar.clicked.connect(self._on_calendar_clicked)
        self._calendar.currentPageChanged.connect(lambda _y, _m: (self._sync_nav_from_calendar(), self._apply_range_format()))

        self._popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._popup.setObjectName("DateSelectPopup")
        pop_lay = QVBoxLayout(self._popup)
        pop_lay.setContentsMargins(10, 10, 10, 10)
        self._hint = QLabel()
        self._hint.setObjectName("DateSelectHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._hint.setProperty("state", "neutral")
        pop_lay.addWidget(self._hint)
        self._nav = QFrame()
        self._nav.setObjectName("DateSelectNav")
        self._nav.setProperty("state", "neutral")
        nav_lay = QHBoxLayout(self._nav)
        nav_lay.setContentsMargins(6, 4, 6, 4)
        nav_lay.setSpacing(8)

        self._prev_btn = QToolButton()
        self._prev_btn.setObjectName("DateSelectNavBtn")
        self._prev_btn.setText(DATE_SELECTOR_PREV_MONTH_TEXT)
        self._prev_btn.clicked.connect(lambda: self._shift_month(-1))

        self._next_btn = QToolButton()
        self._next_btn.setObjectName("DateSelectNavBtn")
        self._next_btn.setText(DATE_SELECTOR_NEXT_MONTH_TEXT)
        self._next_btn.clicked.connect(lambda: self._shift_month(1))

        self._month_combo = QComboBox()
        self._month_combo.setObjectName("DateSelectCombo")
        self._month_combo.setView(QListView())
        self._month_combo.view().setObjectName("DateSelectComboView")
        self._month_combo.view().setTextElideMode(Qt.TextElideMode.ElideNone)
        self._year_combo = QComboBox()
        self._year_combo.setObjectName("DateSelectCombo")
        self._year_combo.setView(QListView())
        self._year_combo.view().setObjectName("DateSelectComboView")
        self._year_combo.view().setTextElideMode(Qt.TextElideMode.ElideNone)

        self._month_names = list(DATE_SELECTOR_MONTH_NAMES)
        self._month_combo.addItems(self._month_names)
        self._year_combo.setEditable(False)
        self._nav_syncing = False
        self._build_years(QDate.currentDate().year())
        self._sync_nav_combo_sizes()

        self._month_combo.currentIndexChanged.connect(self._on_nav_changed)
        self._year_combo.currentIndexChanged.connect(self._on_nav_changed)

        nav_lay.addWidget(self._prev_btn)
        nav_lay.addStretch(1)
        nav_lay.addWidget(self._month_combo)
        nav_lay.addWidget(self._year_combo)
        nav_lay.addStretch(1)
        nav_lay.addWidget(self._next_btn)

        pop_lay.addWidget(self._nav)
        pop_lay.addWidget(self._calendar)

        self._cal_view = None
        self._ensure_calendar_view()
        self._calendar.installEventFilter(self)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_style()
        self._update_label()

    def _apply_style(self):
        self.setStyleSheet("""
        QFrame#DateSelectCard {
            background: #F9FAFB;
            border: 1px solid #E5E7EB;
            border-radius: 14px;
            min-height: 30px;
        }
        QFrame#DateSelectCard:hover {
            background: #FFFFFF;
            border: 1px solid #D0D7E2;
        }
        QFrame#DateSelectCard[focus="true"] {
            border: 1px solid #60A5FA;
            background: #FFFFFF;
        }
        QLabel#DateSelectPlaceholder {
            font-size: 12px;
            font-weight: 600;
            color: #0F172A;
        }
        QLabel#DateSelectBadge {
            background: #EEF2FF;
            border: 1px solid #C7D2FE;
            border-radius: 10px;
            padding: 3px 8px;
            font-size: 12px;
            font-weight: 700;
            color: #1D4ED8;
        }
        QLabel#DateSelectBadge[state="ok"] {
            background: #ECFDF3;
            border: 1px solid #BBF7D0;
            color: #166534;
        }
        QLabel#DateSelectBadge[state="bad"] {
            background: #FEF2F2;
            border: 1px solid #FECACA;
            color: #B91C1C;
        }
        QLabel#DateSelectBadge[state="pending"] {
            background: #DBEAFE;
            border: 1px solid #93C5FD;
            color: #1D4ED8;
        }
        QLabel#DateSelectBadgeGhost {
            background: transparent;
            border: 1px dashed #CBD5E1;
            border-radius: 10px;
            padding: 3px 8px;
            font-size: 12px;
            font-weight: 600;
            color: #64748B;
        }
        QLabel#DateSelectBadgeGhost[state="ok"] {
            border: 1px dashed #86EFAC;
            color: #16A34A;
        }
        QLabel#DateSelectBadgeGhost[state="bad"] {
            border: 1px dashed #FCA5A5;
            color: #DC2626;
        }
        QLabel#DateSelectBadgeGhost[state="pending"] {
            border: 1px dashed #93C5FD;
            color: #2563EB;
        }
        QLabel#DateSelectSeparator {
            font-size: 12px;
            font-weight: 700;
            color: #94A3B8;
        }
        QToolButton#DateSelectIcon {
            border: none;
            background: #EEF2FF;
            min-width: 24px;
            min-height: 24px;
            border-radius: 9px;
            color: #0F172A;
        }
        QToolButton#DateSelectIcon:hover { background: #E0E7FF; }
        QFrame#DateSelectPopup {
            background: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 14px;
        }
        QFrame#DateSelectNav {
            background: #EFF6FF;
            border-radius: 12px;
        }
        QFrame#DateSelectNav[state="ok"] { background: #ECFDF3; }
        QFrame#DateSelectNav[state="bad"] { background: #FEF2F2; }
        QToolButton#DateSelectNavBtn {
            background: #FFFFFF;
            border: 1px solid #BFDBFE;
            border-radius: 12px;
            min-width: 28px;
            min-height: 28px;
            font-size: 16px;
            color: #1D4ED8;
        }
        QToolButton#DateSelectNavBtn:hover { background: #EFF6FF; }
        QComboBox#DateSelectCombo {
            background: #FFFFFF;
            border: 1px solid #BFDBFE;
            border-radius: 10px;
            padding: 4px 10px;
            min-height: 28px;
            font-weight: 700;
            color: #1D4ED8;
        }
        QComboBox#DateSelectCombo::drop-down {
            border: none;
            width: 0px;
            subcontrol-origin: padding;
            subcontrol-position: top right;
        }
        QComboBox#DateSelectCombo::down-arrow {
            image: none;
            width: 0px;
            height: 0px;
            border: none;
        }
        QAbstractItemView#DateSelectComboView {
            background: #FFFFFF;
            border: 1px solid #DBEAFE;
            border-radius: 12px;
            padding: 6px;
            selection-background-color: #3B82F6;
            selection-color: #FFFFFF;
        }
        QListView#DateSelectComboView {
            background: #FFFFFF;
            border: 1px solid #DBEAFE;
            border-radius: 12px;
            padding: 6px;
            selection-background-color: #3B82F6;
            selection-color: #FFFFFF;
            outline: none;
        }
        QLabel#DateSelectHint {
            color: #475569;
            font-size: 11px;
            font-weight: 600;
            padding: 2px 6px;
            background: transparent;
            border-radius: 8px;
        }
        QCalendarWidget QWidget#qt_calendar_navigationbar {
            background: #EFF6FF;
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            padding: 2px 6px;
        }
        QCalendarWidget QToolButton#qt_calendar_prevmonth,
        QCalendarWidget QToolButton#qt_calendar_nextmonth {
            background: #E0F2FE;
            border-radius: 12px;
            min-width: 26px;
            min-height: 26px;
            margin: 4px;
        }
        QCalendarWidget QToolButton#qt_calendar_monthbutton,
        QCalendarWidget QToolButton#qt_calendar_yearbutton {
            border: none;
            background: transparent;
            font-weight: 700;
            padding: 4px 10px;
            color: #1D4ED8;
            min-width: 0px;
        }
        QCalendarWidget QToolButton#qt_calendar_yearbutton {
            min-width: 56px;
        }
        QCalendarWidget QToolButton#qt_calendar_monthbutton:hover,
        QCalendarWidget QToolButton#qt_calendar_yearbutton:hover {
            background: #EFF6FF;
            border-radius: 10px;
        }
        QCalendarWidget QToolButton#qt_calendar_monthbutton::menu-indicator,
        QCalendarWidget QToolButton#qt_calendar_yearbutton::menu-indicator {
            image: none;
            width: 0px;
        }
        QCalendarWidget QSpinBox {
            background: #FFFFFF;
            border: 1px solid #BFDBFE;
            border-radius: 8px;
            min-width: 64px;
            padding: 2px 6px;
        }
        QCalendarWidget QMenu {
            background: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 12px;
            padding: 6px;
        }
        QCalendarWidget QMenu::item {
            padding: 6px 12px;
            border-radius: 8px;
            color: #0F172A;
        }
        QCalendarWidget QMenu::item:selected {
            background: #3B82F6;
            color: #FFFFFF;
        }
        QCalendarWidget QMenu::separator {
            height: 1px;
            background: #E5E7EB;
            margin: 4px 6px;
        }
        QCalendarWidget QToolButton {
            color: #1D4ED8;
            font-weight: 700;
            margin: 4px;
            border: none;
        }
        QCalendarWidget QToolButton:hover { color: #1E40AF; }
        QCalendarWidget QMenu { background: #FFFFFF; }
        QCalendarWidget QSpinBox { margin: 4px; }
        QCalendarWidget QAbstractItemView {
            selection-background-color: #3B82F6;
            selection-color: #FFFFFF;
            font-weight: 600;
        }
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_popup()
        super().mousePressEvent(event)

    def toggle_popup(self):
        if self._popup.isVisible():
            self._popup.hide()
            self._set_focus(False)
            return
        self._set_focus(True)
        self._sync_calendar_selection()
        self._update_hint()
        self._show_popup()

    def _show_popup(self):
        base = self.mapToGlobal(self.rect().bottomLeft())
        self._sync_nav_combo_sizes()
        width = max(self.width(), 280)
        self._popup.setMinimumWidth(width)
        self._popup.adjustSize()
        self._popup.move(base.x(), base.y() + 6)
        self._popup.show()
        self._popup.raise_()
        self._popup.activateWindow()
        self._ensure_calendar_view()

    def _build_years(self, center_year: int):
        with QSignalBlocker(self._year_combo):
            self._year_combo.clear()
            start = center_year - 15
            end = center_year + 15
            for y in range(start, end + 1):
                self._year_combo.addItem(str(y), y)
        self._sync_nav_combo_sizes()

    def _sync_nav_combo_sizes(self):
        month_fm = QFontMetrics(self._month_combo.font())
        month_text_w = max(month_fm.horizontalAdvance(name) for name in self._month_names)
        month_combo_w = max(90, month_text_w + 36)

        year_samples = [self._year_combo.itemText(i) for i in range(self._year_combo.count())]
        if not year_samples:
            year_samples = [str(QDate.currentDate().year())]
        year_fm = QFontMetrics(self._year_combo.font())
        year_text_w = max(year_fm.horizontalAdvance(y) for y in year_samples)
        year_combo_w = max(72, year_text_w + 30)

        self._month_combo.setMinimumWidth(month_combo_w)
        self._year_combo.setMinimumWidth(year_combo_w)

        month_view = self._month_combo.view()
        if month_view is not None:
            month_view.setTextElideMode(Qt.TextElideMode.ElideNone)
            month_view.setMinimumWidth(max(month_combo_w + 16, month_text_w + 24))

        year_view = self._year_combo.view()
        if year_view is not None:
            year_view.setTextElideMode(Qt.TextElideMode.ElideNone)
            year_view.setMinimumWidth(max(year_combo_w + 16, year_text_w + 24))

    def _ensure_year_range(self, year: int):
        values = [self._year_combo.itemData(i) for i in range(self._year_combo.count())]
        if year not in values:
            self._build_years(year)

    def _sync_nav_from_calendar(self):
        if self._nav_syncing:
            return
        self._nav_syncing = True
        year = int(self._calendar.yearShown())
        month = int(self._calendar.monthShown())
        self._ensure_year_range(year)
        self._year_combo.setCurrentText(str(year))
        self._month_combo.setCurrentIndex(month - 1)
        self._nav_syncing = False

    def _on_nav_changed(self):
        if self._nav_syncing:
            return
        try:
            year = int(self._year_combo.currentText())
        except Exception:
            year = int(self._calendar.yearShown())
        month = int(self._month_combo.currentIndex() + 1)
        self._calendar.setCurrentPage(year, month)
        self._apply_range_format()

    def _shift_month(self, delta: int):
        year = int(self._calendar.yearShown())
        month = int(self._calendar.monthShown()) + int(delta)
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1
        self._calendar.setCurrentPage(year, month)
        self._apply_range_format()

    def _ensure_calendar_view(self):
        if self._cal_view is None:
            self._cal_view = self._calendar.findChild(QAbstractItemView)
        if self._cal_view is not None:
            self._cal_view.viewport().setMouseTracking(True)
            self._cal_view.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            self._cal_view.viewport().installEventFilter(self)

    def _set_focus(self, focused: bool):
        self._card.setProperty("focus", bool(focused))
        self._card.style().unpolish(self._card)
        self._card.style().polish(self._card)
        self._card.update()

    def _sync_calendar_selection(self):
        if self._range_enabled:
            if self._start:
                self._calendar.setSelectedDate(self._start)
        else:
            if self._start:
                self._calendar.setSelectedDate(self._start)
        self._apply_range_format()
        self._update_hint()
        self._sync_nav_from_calendar()

    def eventFilter(self, obj, event):
        if obj is self._calendar:
            if not self._popup.isVisible():
                return super().eventFilter(obj, event)
            if event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
                if self._cal_view is not None:
                    pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                    mapped = self._cal_view.viewport().mapFrom(self._calendar, pos)
                    self._on_hover(mapped)
            elif event.type() == QEvent.Type.Leave:
                if self._range_enabled and self._start and self._end is None:
                    self._hover_date = None
                    self._apply_range_format()
            return super().eventFilter(obj, event)
        if self._cal_view is not None and obj is self._cal_view.viewport():
            if not self._popup.isVisible():
                return super().eventFilter(obj, event)
            if event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                self._on_hover(pos)
            elif event.type() == QEvent.Type.Leave:
                if self._range_enabled and self._start and self._end is None:
                    self._hover_date = None
                    self._apply_range_format()
        return super().eventFilter(obj, event)

    def _on_calendar_clicked(self, date: QDate):
        shown_year = int(self._calendar.yearShown())
        shown_month = int(self._calendar.monthShown())
        if int(date.year()) != shown_year or int(date.month()) != shown_month:
            return

        if self._range_enabled:
            if self._start is None or self._end is not None:
                self._start = date
                self._end = None
                self._hover_date = None
                self._calendar.setSelectedDate(self._start)
                self._update_hint()
            else:
                self._end = date
                if self._end < self._start:
                    self._start, self._end = self._end, self._start
                self._hover_date = None
                if not self._suppress:
                    self.rangeChanged.emit(self._start, self._end)
                self._popup.hide()
                self._set_focus(False)
            self._apply_range_format()
            self._update_label()
            return

        self._start = date
        self._end = None
        if not self._suppress:
            self.dateChanged.emit(date)
        self._update_label()
        self._popup.hide()
        self._set_focus(False)

    def _clear_range_format(self):
        fmt = QTextCharFormat()
        for d in (self._formatted_dates + self._dimmed_dates + self._month_hidden_dates):
            self._calendar.setDateTextFormat(d, fmt)
        self._formatted_dates = []
        self._dimmed_dates = []
        self._month_hidden_dates = []

    def _apply_month_only_format(self):
        year = int(self._calendar.yearShown())
        month = int(self._calendar.monthShown())
        hidden_fmt = QTextCharFormat()
        hidden_fmt.setForeground(QBrush(QColor(0, 0, 0, 0)))
        hidden_fmt.setBackground(QBrush(QColor(0, 0, 0, 0)))

        for d in self._visible_dates():
            if int(d.year()) == year and int(d.month()) == month:
                continue
            self._calendar.setDateTextFormat(d, hidden_fmt)
            self._month_hidden_dates.append(QDate(d))

    def _apply_range_format(self):
        self._clear_range_format()
        self._apply_month_only_format()
        if not self._range_enabled or not self._start:
            return
        end = self._end or self._hover_date or self._start
        start = self._start
        if end and start and end < start:
            start, end = end, start

        if self._end is None and self._hover_date is not None:
            dim_fmt = QTextCharFormat()
            dim_fmt.setBackground(QBrush(QColor("#F8FAFC")))
            dim_fmt.setForeground(QBrush(QColor("#CBD5E1")))
            for d in self._visible_dates():
                self._calendar.setDateTextFormat(d, dim_fmt)
                self._dimmed_dates.append(QDate(d))

        mid_fmt = QTextCharFormat()
        mid_fmt.setBackground(QBrush(QColor("#DBEAFE")))
        mid_fmt.setForeground(QBrush(QColor("#1D4ED8")))
        edge_fmt = QTextCharFormat()
        edge_fmt.setBackground(QBrush(QColor("#3B82F6")))
        edge_fmt.setForeground(QBrush(QColor("#FFFFFF")))
        hover_edge_fmt = QTextCharFormat()
        hover_edge_fmt.setBackground(QBrush(QColor("#60A5FA")))
        hover_edge_fmt.setForeground(QBrush(QColor("#FFFFFF")))

        d = QDate(start)
        while d <= end:
            if d == start or d == end:
                if self._end is None and self._hover_date is not None and d == end:
                    self._calendar.setDateTextFormat(d, hover_edge_fmt)
                else:
                    self._calendar.setDateTextFormat(d, edge_fmt)
            else:
                self._calendar.setDateTextFormat(d, mid_fmt)
            self._formatted_dates.append(QDate(d))
            d = d.addDays(1)

    def _update_label(self):
        if self._range_enabled:
            if self._start and self._end:
                start_text = self._start.toString(self._display_format)
                end_text = self._end.toString(self._display_format)
                self._placeholder_label.setVisible(False)
                self._badge_container.setVisible(True)
                self._badge_single.setVisible(False)
                self._badge_start.setVisible(True)
                self._badge_end.setVisible(True)
                self._badge_sep.setVisible(True)
                self._badge_ghost.setVisible(False)
                self._badge_start.setText(start_text)
                self._badge_end.setText(end_text)
            elif self._start:
                start_text = self._start.toString(self._display_format)
                self._placeholder_label.setVisible(False)
                self._badge_container.setVisible(True)
                self._badge_single.setVisible(False)
                self._badge_start.setVisible(True)
                self._badge_end.setVisible(False)
                self._badge_sep.setVisible(True)
                self._badge_ghost.setVisible(True)
                self._badge_start.setText(start_text)
            else:
                self._placeholder_label.setText(self._placeholder)
                self._placeholder_label.setVisible(True)
                self._badge_container.setVisible(False)
        else:
            if self._start:
                single_text = self._start.toString(self._display_format)
                self._placeholder_label.setVisible(False)
                self._badge_container.setVisible(True)
                self._badge_single.setVisible(True)
                self._badge_start.setVisible(False)
                self._badge_end.setVisible(False)
                self._badge_sep.setVisible(False)
                self._badge_ghost.setVisible(False)
                self._badge_single.setText(single_text)
            else:
                self._placeholder_label.setText(self._placeholder)
                self._placeholder_label.setVisible(True)
                self._badge_container.setVisible(False)
        self._apply_badge_state()

    def _update_hint(self):
        if not self._range_enabled:
            self._hint.setVisible(False)
            return
        self._hint.setVisible(True)
        if self._start and self._end:
            self._hint.setText(DATE_SELECTOR_RANGE_SELECTED_HINT_TEXT)
        elif self._start:
            self._hint.setText(DATE_SELECTOR_RANGE_END_HINT_TEXT)
        else:
            self._hint.setText(DATE_SELECTOR_RANGE_START_HINT_TEXT)

    def _on_hover(self, pos: QPoint):
        if not self._popup.isVisible():
            return
        if not self._range_enabled or not self._start or self._end is not None:
            return
        hovered = self._date_at_pos(pos)
        if hovered is None:
            if self._hover_date is not None:
                self._hover_date = None
                self._apply_range_format()
            return
        if self._hover_date != hovered:
            self._hover_date = hovered
            self._apply_range_format()

    def _date_at_pos(self, pos: QPoint) -> QDate | None:
        if self._cal_view is None:
            return None
        idx = self._cal_view.indexAt(pos)
        if not idx.isValid():
            return None
        data = idx.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, QDate) and data.isValid():
            return data

        display = idx.data(Qt.ItemDataRole.DisplayRole)
        if isinstance(display, str):
            if not display.strip().isdigit():
                return None
        elif isinstance(display, (int, float)):
            pass
        else:
            return None

        try:
            model = self._cal_view.model()
            header_rows = max(0, int(model.rowCount()) - 6)
            row = idx.row() - header_rows
            if row < 0:
                return None

            year = int(self._calendar.yearShown())
            month = int(self._calendar.monthShown())
            first = QDate(year, month, 1)
            if not first.isValid():
                return None
            first_dow = first.dayOfWeek()
            week_start = int(self._calendar.firstDayOfWeek().value)
            offset = (first_dow - week_start + 7) % 7
            cell = row * 7 + idx.column()
            picked = first.addDays(cell - offset)
            if int(picked.year()) != year or int(picked.month()) != month:
                return None
            return picked
        except Exception:
            return None

    def _visible_dates(self) -> list[QDate]:
        year = int(self._calendar.yearShown())
        month = int(self._calendar.monthShown())
        first = QDate(year, month, 1)
        if not first.isValid():
            return []
        first_dow = first.dayOfWeek()
        week_start = int(self._calendar.firstDayOfWeek().value)
        offset = (first_dow - week_start + 7) % 7
        start = first.addDays(-offset)
        return [start.addDays(i) for i in range(42)]

    # Public API
    def _apply_badge_state(self):
        pending = self._range_enabled and self._start and self._end is None
        state = "pending" if pending else self._status
        for widget in (self._badge_start, self._badge_end, self._badge_single, self._badge_ghost):
            widget.setProperty("state", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

        if pending and self._badge_ghost.isVisible():
            if self._pulse_anim.state() != QAbstractAnimation.State.Running:
                self._pulse_anim.start()
        else:
            if self._pulse_anim.state() != QAbstractAnimation.State.Stopped:
                self._pulse_anim.stop()
            if self._pulse_effect is not None:
                self._pulse_effect.setOpacity(1.0)

    def setStatus(self, status: str):
        normalized = status if status in ("neutral", "ok", "bad") else "neutral"
        self._status = normalized
        for widget in (self._nav, self._hint):
            widget.setProperty("state", normalized)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        self._apply_badge_state()

    def setDisplayFormat(self, fmt: str):
        self._display_format = fmt or self._display_format
        self._update_label()

    def setRangeEnabled(self, enabled: bool):
        self._range_enabled = bool(enabled)
        self._apply_range_format()
        self._update_label()

    def setDate(self, date_val: QDate):
        self._start = date_val
        self._end = None
        self._hover_date = None
        self._update_label()

    def setRange(self, start: QDate, end: QDate):
        self._start = start
        self._end = end
        self._hover_date = None
        if self._end and self._start and self._end < self._start:
            self._start, self._end = self._end, self._start
        self._apply_range_format()
        self._update_label()

    def date(self) -> QDate:
        return self._start or QDate.currentDate()

    def dateFrom(self) -> QDate:
        return self._start or QDate.currentDate()

    def dateTo(self) -> QDate:
        return self._end or self._start or QDate.currentDate()

    def setSignalsBlocked(self, blocked: bool):
        self._suppress = bool(blocked)


class TimeSelector(QWidget):
    timeChanged = pyqtSignal(QTime)
    rangeChanged = pyqtSignal(QTime, QTime)

    def __init__(
            self,
            parent=None,
            *,
            display_format: str = "HH:mm",
            range_enabled: bool = False,
            placeholder: str = "Saat seç"
    ):
        super().__init__(parent)
        self._suppress = False
        self._display_format = display_format
        self._range_enabled = bool(range_enabled)
        self._placeholder = placeholder
        self._single_time: QTime | None = None
        self._start: QTime | None = None
        self._end: QTime | None = None
        self._syncing = False

        self._card = QFrame()
        self._card.setObjectName("TimeSelectCard")
        self._card.setProperty("focus", False)
        self._card.setCursor(Qt.CursorShape.PointingHandCursor)

        card_layout = QHBoxLayout(self._card)
        card_layout.setContentsMargins(10, 6, 10, 6)
        card_layout.setSpacing(8)

        self._placeholder_label = QLabel()
        self._placeholder_label.setObjectName("TimeSelectPlaceholder")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        self._badge_container = QWidget()
        badges = QHBoxLayout(self._badge_container)
        badges.setContentsMargins(0, 0, 0, 0)
        badges.setSpacing(6)

        self._badge_start = QLabel()
        self._badge_start.setObjectName("TimeSelectBadge")
        self._badge_sep = QLabel(TIME_SELECTOR_RANGE_SEPARATOR_TEXT)
        self._badge_sep.setObjectName("TimeSelectSeparator")
        self._badge_end = QLabel()
        self._badge_end.setObjectName("TimeSelectBadge")
        self._badge_single = QLabel()
        self._badge_single.setObjectName("TimeSelectBadge")

        for widget in (self._badge_start, self._badge_sep, self._badge_end, self._badge_single):
            badges.addWidget(widget)
        self._badge_container.setVisible(False)

        value_wrap = QWidget()
        value_layout = QHBoxLayout(value_wrap)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(6)
        value_layout.addWidget(self._placeholder_label)
        value_layout.addWidget(self._badge_container)

        self._icon = QToolButton()
        self._icon.setObjectName("TimeSelectIcon")
        self._icon.setText(TIME_SELECTOR_ICON_TEXT)
        self._icon.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon.clicked.connect(self.toggle_popup)

        card_layout.addWidget(value_wrap, 1)
        card_layout.addWidget(self._icon, 0)

        base = QVBoxLayout(self)
        base.setContentsMargins(0, 0, 0, 0)
        base.addWidget(self._card)

        self._popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._popup.setObjectName("TimeSelectPopup")
        pop = QVBoxLayout(self._popup)
        pop.setContentsMargins(10, 10, 10, 10)
        pop.setSpacing(8)

        self._hint = QLabel()
        self._hint.setObjectName("TimeSelectHint")
        pop.addWidget(self._hint)

        self._single_panel = QFrame()
        self._single_panel.setObjectName("TimeSelectRow")
        single_layout = QHBoxLayout(self._single_panel)
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.setSpacing(6)
        self._single_hour = self._create_time_combo()
        self._single_minute = self._create_time_combo(max_value=59)
        colon1 = QLabel(":")
        colon1.setObjectName("TimeSelectColon")
        single_layout.addWidget(self._single_hour, 1)
        single_layout.addWidget(colon1, 0, Qt.AlignmentFlag.AlignCenter)
        single_layout.addWidget(self._single_minute, 1)
        pop.addWidget(self._single_panel)

        self._range_panel = QFrame()
        self._range_panel.setObjectName("TimeSelectRangePanel")
        range_layout = QVBoxLayout(self._range_panel)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(6)

        self._range_start_hour = self._create_time_combo()
        self._range_start_minute = self._create_time_combo(max_value=59)
        start_row = self._build_range_row(TIME_SELECTOR_START_LABEL, self._range_start_hour, self._range_start_minute)
        self._range_end_hour = self._create_time_combo()
        self._range_end_minute = self._create_time_combo(max_value=59)
        end_row = self._build_range_row(TIME_SELECTOR_END_LABEL, self._range_end_hour, self._range_end_minute)
        range_layout.addWidget(start_row)
        range_layout.addWidget(end_row)
        pop.addWidget(self._range_panel)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        self._now_btn = QToolButton()
        self._now_btn.setObjectName("TimeSelectAction")
        self._now_btn.setText(TIME_SELECTOR_NOW_TEXT)
        self._ok_btn = QToolButton()
        self._ok_btn.setObjectName("TimeSelectAction")
        self._ok_btn.setText(TIME_SELECTOR_OK_TEXT)
        actions.addWidget(self._now_btn)
        actions.addWidget(self._ok_btn)
        pop.addLayout(actions)

        self._single_hour.currentIndexChanged.connect(self._on_single_combo_changed)
        self._single_minute.currentIndexChanged.connect(self._on_single_combo_changed)
        self._range_start_hour.currentIndexChanged.connect(self._on_range_combo_changed)
        self._range_start_minute.currentIndexChanged.connect(self._on_range_combo_changed)
        self._range_end_hour.currentIndexChanged.connect(self._on_range_combo_changed)
        self._range_end_minute.currentIndexChanged.connect(self._on_range_combo_changed)
        self._now_btn.clicked.connect(self._set_now)
        self._ok_btn.clicked.connect(self._close_popup)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_style()
        self._sync_panels()
        self._update_label()

    def _create_time_combo(self, *, max_value: int = 23) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName("TimeSelectCombo")
        combo.setView(QListView())
        combo.view().setObjectName("TimeSelectComboView")
        for value in range(0, int(max_value) + 1):
            combo.addItem(f"{value:02d}", value)
        return combo

    def _build_range_row(self, title: str, hour_combo: QComboBox, minute_combo: QComboBox) -> QWidget:
        row = QFrame()
        row.setObjectName("TimeSelectRangeRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("TimeSelectRangeLabel")
        colon = QLabel(":")
        colon.setObjectName("TimeSelectColon")
        layout.addWidget(label, 0)
        layout.addWidget(hour_combo, 1)
        layout.addWidget(colon, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(minute_combo, 1)
        return row

    def _apply_style(self):
        self.setStyleSheet("""
        QFrame#TimeSelectCard {
            background: #F9FAFB;
            border: 1px solid #E5E7EB;
            border-radius: 14px;
            min-height: 30px;
        }
        QFrame#TimeSelectCard:hover {
            background: #FFFFFF;
            border: 1px solid #D0D7E2;
        }
        QFrame#TimeSelectCard[focus="true"] {
            border: 1px solid #60A5FA;
            background: #FFFFFF;
        }
        QLabel#TimeSelectPlaceholder {
            font-size: 12px;
            font-weight: 600;
            color: #0F172A;
        }
        QLabel#TimeSelectBadge {
            background: #EEF2FF;
            border: 1px solid #C7D2FE;
            border-radius: 10px;
            padding: 3px 8px;
            font-size: 12px;
            font-weight: 700;
            color: #1D4ED8;
        }
        QLabel#TimeSelectSeparator {
            font-size: 12px;
            font-weight: 700;
            color: #94A3B8;
        }
        QToolButton#TimeSelectIcon {
            border: none;
            background: #EEF2FF;
            min-width: 24px;
            min-height: 24px;
            border-radius: 9px;
            color: #0F172A;
        }
        QToolButton#TimeSelectIcon:hover { background: #E0E7FF; }
        QFrame#TimeSelectPopup {
            background: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 14px;
        }
        QLabel#TimeSelectHint {
            color: #475569;
            font-size: 11px;
            font-weight: 600;
            padding: 2px 6px;
        }
        QLabel#TimeSelectColon {
            color: #1D4ED8;
            font-weight: 900;
            font-size: 15px;
            min-width: 8px;
        }
        QLabel#TimeSelectRangeLabel {
            color: #1E293B;
            font-size: 11px;
            font-weight: 700;
            min-width: 58px;
        }
        QComboBox#TimeSelectCombo {
            background: #FFFFFF;
            border: 1px solid #BFDBFE;
            border-radius: 10px;
            padding: 4px 10px;
            min-height: 28px;
            font-weight: 700;
            color: #1D4ED8;
        }
        QComboBox#TimeSelectCombo::drop-down {
            border: none;
            width: 0px;
            subcontrol-origin: padding;
            subcontrol-position: top right;
        }
        QComboBox#TimeSelectCombo::down-arrow {
            image: none;
            width: 0px;
            height: 0px;
            border: none;
        }
        QListView#TimeSelectComboView,
        QAbstractItemView#TimeSelectComboView {
            background: #FFFFFF;
            border: 1px solid #DBEAFE;
            border-radius: 12px;
            padding: 4px;
            selection-background-color: #3B82F6;
            selection-color: #FFFFFF;
            outline: none;
        }
        QToolButton#TimeSelectAction {
            background: #EEF2FF;
            border: 1px solid #C7D2FE;
            border-radius: 9px;
            min-width: 64px;
            min-height: 26px;
            font-size: 11px;
            font-weight: 700;
            color: #1D4ED8;
        }
        QToolButton#TimeSelectAction:hover { background: #E0E7FF; }
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_popup()
        super().mousePressEvent(event)

    def toggle_popup(self):
        if self._popup.isVisible():
            self._close_popup()
            return
        self._set_focus(True)
        self._sync_controls_from_values()
        self._show_popup()

    def _show_popup(self):
        base = self.mapToGlobal(self.rect().bottomLeft())
        width = max(self.width(), 260 if self._range_enabled else 220)
        self._popup.setMinimumWidth(width)
        self._popup.adjustSize()
        self._popup.move(base.x(), base.y() + 6)
        self._popup.show()
        self._popup.raise_()
        self._popup.activateWindow()

    def _close_popup(self):
        self._popup.hide()
        self._set_focus(False)

    def _set_focus(self, focused: bool):
        self._card.setProperty("focus", bool(focused))
        self._card.style().unpolish(self._card)
        self._card.style().polish(self._card)
        self._card.update()

    def _sync_panels(self):
        self._single_panel.setVisible(not self._range_enabled)
        self._range_panel.setVisible(self._range_enabled)
        self._update_hint()

    def _set_combo_time(self, hour_combo: QComboBox, minute_combo: QComboBox, value: QTime):
        h = max(0, min(23, int(value.hour())))
        m = max(0, min(59, int(value.minute())))
        hour_combo.setCurrentIndex(h)
        minute_combo.setCurrentIndex(m)

    def _read_combo_time(self, hour_combo: QComboBox, minute_combo: QComboBox) -> QTime:
        hour = int(hour_combo.currentData() if hour_combo.currentData() is not None else hour_combo.currentIndex())
        minute = int(minute_combo.currentData() if minute_combo.currentData() is not None else minute_combo.currentIndex())
        return QTime(hour, minute)

    def _sync_controls_from_values(self):
        self._syncing = True
        if self._range_enabled:
            start = self._start if self._start and self._start.isValid() else QTime.currentTime()
            end = self._end if self._end and self._end.isValid() else start
            self._set_combo_time(self._range_start_hour, self._range_start_minute, start)
            self._set_combo_time(self._range_end_hour, self._range_end_minute, end)
        else:
            value = self._single_time if self._single_time and self._single_time.isValid() else QTime.currentTime()
            self._set_combo_time(self._single_hour, self._single_minute, value)
        self._syncing = False

    def _on_single_combo_changed(self):
        if self._syncing:
            return
        self._single_time = self._read_combo_time(self._single_hour, self._single_minute)
        self._update_label()
        if not self._suppress:
            self.timeChanged.emit(self._single_time)

    def _on_range_combo_changed(self):
        if self._syncing:
            return
        start = self._read_combo_time(self._range_start_hour, self._range_start_minute)
        end = self._read_combo_time(self._range_end_hour, self._range_end_minute)
        if end < start:
            start, end = end, start
            self._syncing = True
            self._set_combo_time(self._range_start_hour, self._range_start_minute, start)
            self._set_combo_time(self._range_end_hour, self._range_end_minute, end)
            self._syncing = False
        self._start = start
        self._end = end
        self._update_label()
        if not self._suppress:
            self.rangeChanged.emit(self._start, self._end)

    def _set_now(self):
        now = QTime.currentTime()
        if self._range_enabled:
            self._start = now
            self._end = now
            self._sync_controls_from_values()
            self._update_label()
            if not self._suppress:
                self.rangeChanged.emit(self._start, self._end)
        else:
            self._single_time = now
            self._sync_controls_from_values()
            self._update_label()
            if not self._suppress:
                self.timeChanged.emit(self._single_time)

    def _update_hint(self):
        if self._range_enabled:
            self._hint.setText(TIME_SELECTOR_RANGE_HINT_TEXT)
        else:
            self._hint.setText(TIME_SELECTOR_SINGLE_HINT_TEXT)

    def _update_label(self):
        self._update_hint()
        if self._range_enabled:
            if self._start and self._start.isValid() and self._end and self._end.isValid():
                self._placeholder_label.setVisible(False)
                self._badge_container.setVisible(True)
                self._badge_single.setVisible(False)
                self._badge_start.setVisible(True)
                self._badge_sep.setVisible(True)
                self._badge_end.setVisible(True)
                self._badge_start.setText(self._start.toString(self._display_format))
                self._badge_end.setText(self._end.toString(self._display_format))
            else:
                self._placeholder_label.setVisible(True)
                self._placeholder_label.setText(self._placeholder)
                self._badge_container.setVisible(False)
        else:
            if self._single_time and self._single_time.isValid():
                self._placeholder_label.setVisible(False)
                self._badge_container.setVisible(True)
                self._badge_start.setVisible(False)
                self._badge_sep.setVisible(False)
                self._badge_end.setVisible(False)
                self._badge_single.setVisible(True)
                self._badge_single.setText(self._single_time.toString(self._display_format))
            else:
                self._placeholder_label.setVisible(True)
                self._placeholder_label.setText(self._placeholder)
                self._badge_container.setVisible(False)

    def setDisplayFormat(self, fmt: str):
        self._display_format = fmt or self._display_format
        self._update_label()

    def setRangeEnabled(self, enabled: bool):
        self._range_enabled = bool(enabled)
        self._sync_panels()
        self._sync_controls_from_values()
        self._update_label()

    def setTime(self, time_val: QTime):
        self._single_time = time_val if isinstance(time_val, QTime) and time_val.isValid() else None
        self._sync_controls_from_values()
        self._update_label()

    def time(self) -> QTime:
        if self._single_time and self._single_time.isValid():
            return QTime(self._single_time.hour(), self._single_time.minute(), self._single_time.second())
        return QTime.currentTime()

    def setRange(self, start: QTime, end: QTime):
        start_ok = start if isinstance(start, QTime) and start.isValid() else None
        end_ok = end if isinstance(end, QTime) and end.isValid() else None
        if start_ok and end_ok and end_ok < start_ok:
            start_ok, end_ok = end_ok, start_ok
        self._start = start_ok
        self._end = end_ok
        self._sync_controls_from_values()
        self._update_label()

    def timeFrom(self) -> QTime:
        if self._start and self._start.isValid():
            return QTime(self._start.hour(), self._start.minute(), self._start.second())
        return QTime.currentTime()

    def timeTo(self) -> QTime:
        if self._end and self._end.isValid():
            return QTime(self._end.hour(), self._end.minute(), self._end.second())
        if self._start and self._start.isValid():
            return self.timeFrom()
        return QTime.currentTime()

    def setSignalsBlocked(self, blocked: bool):
        self._suppress = bool(blocked)
