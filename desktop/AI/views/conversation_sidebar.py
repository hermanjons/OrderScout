"""A local, presentation-only conversation list for the desktop chat surface."""
from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from html import escape
import unicodedata

from PyQt6.QtCore import QEvent, QSignalBlocker, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)


_GROUPS = ("BUGÜN", "DÜN", "BU HAFTA", "DAHA ESKİ")
_MONTHS = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
           "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _search_text(value: str) -> str:
    # Fold dotted and dotless Turkish capitals before Unicode's default casefold.
    return unicodedata.normalize("NFKC", value).translate(str.maketrans({"İ": "i", "I": "ı"})).casefold()


def _title(row: dict) -> str:
    for key in ("title", "goal"):
        title = " ".join(str(row.get(key) or "").split())
        if title:
            return title
    return "Yeni sohbet"


def _timestamp(row: dict, local_timezone: tzinfo | None) -> datetime | None:
    for key in ("updated_at", "created_at"):
        value = row.get(key)
        try:
            stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp.astimezone(local_timezone)
        except (ValueError, TypeError, OverflowError, OSError):
            continue
    return None


def _group(stamp: datetime | None, now: datetime) -> str:
    if stamp is None:
        return _GROUPS[3]
    days = (now.date() - stamp.date()).days
    return _GROUPS[0] if days <= 0 else _GROUPS[1] if days == 1 else _GROUPS[2] if days < 7 else _GROUPS[3]


def _date_text(stamp: datetime | None, now: datetime) -> str:
    if stamp is None:
        return "Tarih yok"
    if (now.date() - stamp.date()).days <= 1:
        return stamp.strftime("%H:%M")
    return f"{stamp.day} {_MONTHS[stamp.month - 1]}" + (f" {stamp.year}" if stamp.year != now.year else "")


def _tooltip(text: str) -> str:
    # Qt tooltips detect HTML automatically; escape stored titles before display.
    return f"<qt>{escape(text)}</qt>"


class _ElidedLabel(QLabel):
    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.full_text = text
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setToolTip(_tooltip(text))
        self.setAccessibleName(text)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and hasattr(self, "full_text"):
            self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideRight, self.width()))


class _ConversationRow(QFrame):
    def __init__(self, title: str, metadata: str, *, pending: bool, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("conversationRow")
        self.setProperty("active", False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName(f"{title}, {metadata}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 10, 8)
        layout.setSpacing(9)
        accent = QFrame(self)
        accent.setObjectName("conversationAccent")
        accent.setFixedSize(2, 28)
        layout.addWidget(accent)
        labels = QVBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(4)
        self.title_label = _ElidedLabel(title, self)
        self.title_label.setObjectName("conversationTitle")
        self.meta_label = QLabel(metadata, self)
        self.meta_label.setObjectName("conversationMeta")
        self.meta_label.setTextFormat(Qt.TextFormat.PlainText)
        self.meta_label.setProperty("pending", pending)
        labels.addWidget(self.title_label)
        labels.addWidget(self.meta_label)
        layout.addLayout(labels, 1)

    def set_active(self, active: bool) -> None:
        if self.property("active") == active:
            return
        self.setProperty("active", active)
        for widget in (self, *self.findChildren(QWidget)):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()


class ConversationSidebar(QFrame):
    session_requested = pyqtSignal(str)
    new_chat_requested = pyqtSignal()
    workflows_requested = pyqtSignal()
    schedules_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._active_session_id = ""
        self._busy = False
        self.setObjectName("conversationSidebar")
        self.setAccessibleName("Sohbetler")
        self.setMinimumWidth(200)
        self.setMaximumWidth(300)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(15, 14, 11, 5)
        heading = QLabel("Sohbetler", self)
        heading.setObjectName("conversationHeading")
        header.addWidget(heading, 1)
        self.new_chat_button = QToolButton(self)
        self.new_chat_button.setObjectName("conversationNewChat")
        self.new_chat_button.setText("+")
        self.new_chat_button.setFixedSize(28, 28)
        self.new_chat_button.setToolTip("Yeni sohbet")
        self.new_chat_button.setAccessibleName("Yeni sohbet")
        self.new_chat_button.clicked.connect(lambda: self._request_action(self.new_chat_requested))
        header.addWidget(self.new_chat_button)
        layout.addLayout(header)

        search_area = QHBoxLayout()
        search_area.setContentsMargins(14, 0, 14, 17)
        search = QFrame(self)
        search.setObjectName("conversationSearch")
        search_layout = QHBoxLayout(search)
        search_layout.setContentsMargins(0, 6, 0, 8)
        search_layout.setSpacing(8)
        icon = QLabel(search)
        icon.setPixmap(self._search_icon())
        search_layout.addWidget(icon)
        self.search_field = QLineEdit(search)
        self.search_field.setObjectName("conversationSearchField")
        self.search_field.setPlaceholderText("Sohbetlerde ara")
        self.search_field.setAccessibleName("Sohbetlerde ara")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.textChanged.connect(lambda: self._render_sessions(preserve_scroll=False))
        search_layout.addWidget(self.search_field, 1)
        search_area.addWidget(search)
        layout.addLayout(search_area)

        self._content = QStackedWidget(self)
        self.session_list = QListWidget(self._content)
        self.session_list.setObjectName("conversationList")
        self.session_list.setAccessibleName("Kayıtlı sohbetler")
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.session_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.session_list.itemClicked.connect(self._request_session)
        self.session_list.itemSelectionChanged.connect(self._sync_selection)
        self.session_list.installEventFilter(self)
        self._content.addWidget(self.session_list)
        self._empty_label = QLabel("Henüz sohbet yok.", self._content)
        self._empty_label.setObjectName("conversationEmpty")
        self._empty_label.setTextFormat(Qt.TextFormat.PlainText)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._empty_label.setWordWrap(True)
        self._content.addWidget(self._empty_label)
        layout.addWidget(self._content, 1)

        footer = QFrame(self)
        footer.setObjectName("conversationFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 12, 14, 12)
        footer_layout.setSpacing(2)
        self.workflows_button = QPushButton("Yönergeler", footer)
        self.workflows_button.setAccessibleName("Kayıtlı yönergeleri aç")
        self.workflows_button.clicked.connect(lambda: self._request_action(self.workflows_requested))
        self.schedules_button = QPushButton("Planlar", footer)
        self.schedules_button.setAccessibleName("Zamanlanmış planları aç")
        self.schedules_button.clicked.connect(lambda: self._request_action(self.schedules_requested))
        footer_layout.addWidget(self.workflows_button)
        footer_layout.addWidget(self.schedules_button)
        footer_layout.addStretch(1)
        layout.addWidget(footer)
        self._render_sessions(preserve_scroll=False)

    def sizeHint(self) -> QSize:
        return QSize(242, super().sizeHint().height())

    @staticmethod
    def _search_icon() -> QPixmap:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#94A3B8"), 1.3))
        painter.drawEllipse(2, 2, 9, 9)
        painter.drawLine(10, 10, 14, 14)
        painter.end()
        return pixmap

    def set_sessions(self, rows: list[dict], active_session_id: str = "") -> None:
        preserve_scroll = bool(self._rows)
        seen: set[str] = set()
        self._rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            session_id = str(row.get("session_id") or "")
            if session_id and session_id not in seen:
                self._rows.append(dict(row, session_id=session_id))
                seen.add(session_id)
        self._active_session_id = str(active_session_id or "")
        self._render_sessions(preserve_scroll=preserve_scroll)

    def set_busy(self, busy: bool) -> None:
        busy = bool(busy)
        if self._busy == busy:
            return
        self._busy = busy
        for widget in (self.session_list, self.new_chat_button, self.workflows_button, self.schedules_button):
            widget.setEnabled(not busy)
        self._render_sessions(preserve_scroll=True)

    def _status_text(self, row: dict) -> tuple[str, bool]:
        try:
            pending = int(row.get("pending_count") or 0) > 0
        except (ValueError, TypeError, OverflowError):
            pending = False
        status = str(row.get("status") or "").casefold()
        if self._busy and row["session_id"] == self._active_session_id:
            return "Çalışıyor", False
        if pending or status in {"pending_approval", "awaiting_approval", "approval_required"}:
            return "Onay bekliyor", True
        return {"running": "Yarım kaldı", "interrupted": "Yarım kaldı", "paused": "Duraklatıldı",
                "complete": "Tamamlandı", "completed": "Tamamlandı", "failed": "Tamamlanamadı",
                "cancelled": "İptal edildi", "canceled": "İptal edildi", "blocked": "Bekliyor"}.get(status, "Kaydedildi"), False

    def _render_sessions(self, *, preserve_scroll: bool) -> None:
        scroll = self.session_list.verticalScrollBar().value()
        now = _local_now()
        query = _search_text(self.search_field.text().strip())
        groups: dict[str, list[tuple[dict, datetime | None]]] = {name: [] for name in _GROUPS}
        for row in self._rows:
            if query and query not in _search_text(_title(row)):
                continue
            stamp = _timestamp(row, now.tzinfo)
            groups[_group(stamp, now)].append((row, stamp))
        with QSignalBlocker(self.session_list):
            self.session_list.clear()
            active_item = None
            for name, rows in groups.items():
                if not rows:
                    continue
                heading = QListWidgetItem(name)
                heading.setFlags(Qt.ItemFlag.NoItemFlags)
                heading.setForeground(QColor("#94A3B8"))
                font = heading.font()
                font.setPixelSize(10)
                font.setWeight(600)
                heading.setFont(font)
                heading.setSizeHint(QSize(0, 29))
                self.session_list.addItem(heading)
                rows.sort(key=lambda pair: pair[1].timestamp() if pair[1] else float("-inf"), reverse=True)
                for row, stamp in rows:
                    title = _title(row)
                    status, pending = self._status_text(row)
                    metadata = f"{_date_text(stamp, now)} · {status}"
                    item = QListWidgetItem()
                    item.setData(Qt.ItemDataRole.UserRole, str(row["session_id"]))
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{title}, {metadata}")
                    item.setToolTip(_tooltip(title))
                    item.setSizeHint(QSize(0, 55))
                    self.session_list.addItem(item)
                    self.session_list.setItemWidget(item, _ConversationRow(title, metadata, pending=pending, parent=self.session_list))
                    if str(row["session_id"]) == self._active_session_id:
                        active_item = item
            self.session_list.setCurrentItem(active_item)
            if active_item is None:
                self.session_list.clearSelection()
            self.session_list.doItemsLayout()
            if preserve_scroll:
                self.session_list.verticalScrollBar().setValue(scroll)
            elif active_item is not None and not query:
                self.session_list.scrollToItem(active_item)
            else:
                self.session_list.scrollToTop()
        self._sync_selection()
        has_sessions = any(groups.values())
        self._empty_label.setText("Eşleşen sohbet bulunamadı." if query else "Henüz sohbet yok.")
        self._content.setCurrentIndex(0 if has_sessions else 1)

    def _sync_selection(self) -> None:
        for index in range(self.session_list.count()):
            item = self.session_list.item(index)
            widget = self.session_list.itemWidget(item)
            if isinstance(widget, _ConversationRow):
                widget.set_active(item.isSelected())

    def _request_session(self, item: QListWidgetItem) -> None:
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if self._busy or not session_id:
            return
        self._active_session_id = str(session_id)
        self.session_requested.emit(str(session_id))

    def _request_action(self, signal) -> None:
        if not self._busy:
            signal.emit()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.session_list and event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space,
        ):
            item = self.session_list.currentItem()
            if item is not None:
                self._request_session(item)
            return True
        return super().eventFilter(watched, event)


_STYLE = """
QFrame#conversationSidebar {background:#F8FAFD; border:1px solid #DFE6EF; border-radius:13px;}
QLabel#conversationHeading {color:#0F172A; font-size:14px; font-weight:600; border:0; background:transparent;}
QToolButton#conversationNewChat {color:#334155; font-size:22px; border:0; border-radius:7px; background:transparent;}
QToolButton#conversationNewChat:hover {background:#EFF3F8;}
QToolButton#conversationNewChat:disabled {color:#94A3B8;}
QFrame#conversationSearch {background:transparent; border:0; border-bottom:1px solid #DFE6EF; border-radius:0;}
QFrame#conversationSearch QLabel {background:transparent; border:0;}
QLineEdit#conversationSearchField {background:transparent; color:#0F172A; font-size:12px; border:0; padding:0;}
QListWidget#conversationList {background:transparent; border:0; padding:0 8px; outline:0;}
QListWidget#conversationList::item {border:0; border-radius:7px; padding:0;}
QListWidget#conversationList::item:selected {background:transparent;}
QListWidget#conversationList::item:hover:enabled {background:#EFF3F8;}
QFrame#conversationRow {background:transparent; border:0; border-radius:7px;}
QFrame#conversationRow[active="true"] {background:#EAF1FE;}
QFrame#conversationAccent {background:transparent; border:0; border-radius:1px;}
QFrame#conversationRow[active="true"] QFrame#conversationAccent {background:#2563EB;}
QLabel#conversationTitle {color:#0F172A; font-size:12px; border:0; background:transparent;}
QLabel#conversationMeta {color:#94A3B8; font-size:10px; border:0; background:transparent;}
QFrame#conversationRow[active="true"] QLabel#conversationTitle {color:#1D4ED8; font-weight:600;}
QFrame#conversationRow[active="true"] QLabel#conversationMeta {color:#6B88B5;}
QFrame#conversationRow QLabel#conversationMeta[pending="true"] {color:#A16207;}
QLabel#conversationEmpty {color:#94A3B8; font-size:12px; padding:12px 18px; border:0; background:transparent;}
QFrame#conversationFooter {background:transparent; border:0; border-top:1px solid #E5EBF3; border-radius:0;}
QFrame#conversationFooter QPushButton {color:#64748B; font-size:11px; background:transparent; border:0; border-radius:6px; padding:7px 8px;}
QFrame#conversationFooter QPushButton:hover {background:#EFF3F8;}
QFrame#conversationFooter QPushButton:disabled {color:#94A3B8;}
QFrame#conversationSidebar QToolButton:focus, QFrame#conversationSidebar QPushButton:focus {border:1px solid #93C5FD;}
"""
