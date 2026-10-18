from __future__ import annotations
from .views import *

def _manager_record_id(record: Any) -> Optional[int]:
    if isinstance(record, dict):
        value = record.get("pk")
    else:
        value = getattr(record, "pk", None)
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed != 0 else None


class ManagerCardsListModel(QAbstractListModel):
    TitleRole = Qt.ItemDataRole.UserRole + 201
    SubtitleRole = Qt.ItemDataRole.UserRole + 202
    ExtraRole = Qt.ItemDataRole.UserRole + 203
    BadgeRole = Qt.ItemDataRole.UserRole + 204
    RecordRole = Qt.ItemDataRole.UserRole + 205
    SelectedRole = Qt.ItemDataRole.UserRole + 206
    PlaceholderRole = Qt.ItemDataRole.UserRole + 207
    ActiveRole = Qt.ItemDataRole.UserRole + 208
    BulkSelectedRole = Qt.ItemDataRole.UserRole + 209

    def __init__(self, records: list[dict[str, Any]] | None = None, parent=None, *, on_selection_changed=None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._has_placeholder = False
        self._on_selection_changed = on_selection_changed
        self._active_row: int = -1
        self._bulk_selected_rows: set[int] = set()
        self._row_by_id: dict[int, int] = {}
        self.set_items(records or [])

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._rows):
            return None
        item = self._rows[row]

        if item.get("placeholder"):
            if role in (Qt.ItemDataRole.DisplayRole, self.TitleRole):
                return item.get("title") or ""
            if role == self.PlaceholderRole:
                return True
            return None

        if role in (Qt.ItemDataRole.DisplayRole, self.TitleRole):
            return item.get("title") or ""
        if role == self.SubtitleRole:
            return item.get("subtitle") or ""
        if role == self.ExtraRole:
            return item.get("extra") or ""
        if role == self.BadgeRole:
            return item.get("badge") or ""
        if role == self.RecordRole:
            return item.get("record")
        if role == self.SelectedRole:
            return row == self._active_row
        if role == self.PlaceholderRole:
            return False
        if role == self.ActiveRole:
            return row == self._active_row
        if role == self.BulkSelectedRole:
            return row in self._bulk_selected_rows
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled

    @staticmethod
    def _safe_record_id(value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    def set_items(
        self,
        records: list[dict[str, Any]],
        *,
        selected_id: Optional[int] = None,
        bulk_selected_ids: Optional[list[int]] = None,
    ) -> None:
        keep_selected_id = self._safe_record_id(selected_id)
        keep_bulk_ids = {
            rid
            for rid in (self._safe_record_id(v) for v in (bulk_selected_ids or []))
            if rid is not None
        }
        self.beginResetModel()
        if records:
            rows: list[dict[str, Any]] = []
            active_row = -1
            bulk_rows: set[int] = set()
            row_by_id: dict[int, int] = {}
            for idx, rec in enumerate(records):
                rid = self._safe_record_id(_manager_record_id(rec))
                if rid is not None:
                    row_by_id[rid] = idx
                title = str(rec.get("title") or rec.get("name") or "").strip() or f"#{rid if rid is not None else '-'}"
                subtitle = str(rec.get("subtitle") or "").strip()
                extra = str(rec.get("extra") or "").strip()
                badge = str(rec.get("badge") or "").strip()
                if keep_selected_id is not None and rid == keep_selected_id:
                    active_row = idx
                if rid is not None and rid in keep_bulk_ids:
                    bulk_rows.add(idx)
                rows.append(
                    {
                        "record": rec,
                        "title": title,
                        "subtitle": subtitle,
                        "extra": extra,
                        "badge": badge,
                    }
                )
            self._rows = rows
            self._has_placeholder = False
            self._active_row = active_row
            self._bulk_selected_rows = bulk_rows
            self._row_by_id = row_by_id
        else:
            self._rows = [{"placeholder": True, "title": STOCK_MANAGER_EMPTY_TEXT}]
            self._has_placeholder = True
            self._active_row = -1
            self._bulk_selected_rows = set()
            self._row_by_id = {}
        self.endResetModel()

    def selected_record(self) -> Optional[dict[str, Any]]:
        if self._has_placeholder or self._active_row < 0 or self._active_row >= len(self._rows):
            return None
        rec = self._rows[self._active_row].get("record")
        return rec if isinstance(rec, dict) else None

    def selected_record_id(self) -> Optional[int]:
        rec = self.selected_record()
        if rec is None:
            return None
        return self._safe_record_id(_manager_record_id(rec))

    def set_selected(self, row: int, selected: bool) -> None:
        self.set_active_row(row if bool(selected) else -1)

    def set_active_row(self, row: int) -> None:
        if self._has_placeholder:
            row = -1
        if row < 0 or row >= len(self._rows):
            row = -1
        elif self._rows[row].get("placeholder"):
            row = -1

        if self._active_row == row:
            return

        prev = self._active_row
        self._active_row = row
        if prev >= 0:
            prev_idx = self.index(prev)
            self.dataChanged.emit(prev_idx, prev_idx, [self.SelectedRole, self.ActiveRole])
        if row >= 0:
            cur_idx = self.index(row)
            self.dataChanged.emit(cur_idx, cur_idx, [self.SelectedRole, self.ActiveRole])
        if self._on_selection_changed:
            self._on_selection_changed()

    def set_selected_by_id(self, record_id: Optional[int]) -> bool:
        sid = self._safe_record_id(record_id)
        if sid is None:
            self.clear_active_row()
            return False
        row = self._row_by_id.get(sid)
        if row is not None:
            self.set_active_row(row)
            return True
        self.clear_active_row()
        return False

    def clear_active_row(self) -> None:
        if self._active_row < 0:
            return
        prev = self._active_row
        self._active_row = -1
        if prev >= 0:
            idx = self.index(prev)
            self.dataChanged.emit(idx, idx, [self.SelectedRole, self.ActiveRole])
        if self._on_selection_changed:
            self._on_selection_changed()

    def active_row(self) -> int:
        return self._active_row

    def set_bulk_selected_row(self, row: int, selected: bool) -> bool:
        if row < 0 or row >= len(self._rows):
            return False
        if self._rows[row].get("placeholder"):
            return False
        prev = row in self._bulk_selected_rows
        next_state = bool(selected)
        if prev == next_state:
            return prev
        if next_state:
            self._bulk_selected_rows.add(row)
        else:
            self._bulk_selected_rows.discard(row)
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [self.BulkSelectedRole])
        if self._on_selection_changed:
            self._on_selection_changed()
        return next_state

    def clear_bulk_selected_rows(self) -> None:
        if not self._bulk_selected_rows:
            return
        rows = sorted(self._bulk_selected_rows)
        self._bulk_selected_rows.clear()
        for row in rows:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [self.BulkSelectedRole])
        if self._on_selection_changed:
            self._on_selection_changed()

    def bulk_selected_records(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in sorted(self._bulk_selected_rows):
            if 0 <= row < len(self._rows):
                rec = self._rows[row].get("record")
                if isinstance(rec, dict):
                    out.append(rec)
        return out

    def bulk_selected_ids(self) -> list[int]:
        ids: list[int] = []
        for rec in self.bulk_selected_records():
            rid = self._safe_record_id(_manager_record_id(rec))
            if rid is not None:
                ids.append(rid)
        return ids

    def bulk_selected_count(self) -> int:
        return len(self._bulk_selected_rows)

    def visible_count(self) -> int:
        if self._has_placeholder:
            return 0
        return len(self._rows)


class ManagerCardsListDelegate(RecordWorkspaceListDelegate):
    def __init__(self, parent=None, *, on_select_button=None):
        super().__init__(parent, on_select_button=on_select_button)
        self._row_height = STOCK_MANAGER_CARD_ROW_HEIGHT

    def _is_placeholder_index(self, index: QModelIndex) -> bool:
        return bool(index.data(ManagerCardsListModel.PlaceholderRole))

    def _is_selected_index(self, index: QModelIndex) -> bool:
        return bool(index.data(ManagerCardsListModel.BulkSelectedRole))

    def _is_active_index(self, index: QModelIndex) -> bool:
        return bool(index.data(ManagerCardsListModel.ActiveRole))

    def _is_hook_selected_index(self, index: QModelIndex) -> bool:
        return bool(index.data(ManagerCardsListModel.BulkSelectedRole))

    def _paint_card_content(self, painter: QPainter, rect: QRect, index: QModelIndex, hook_rect: QRect) -> None:
        title = index.data(ManagerCardsListModel.TitleRole) or ""
        subtitle = index.data(ManagerCardsListModel.SubtitleRole) or ""
        extra = index.data(ManagerCardsListModel.ExtraRole) or ""
        badge = str(index.data(ManagerCardsListModel.BadgeRole) or "").strip()

        avatar_rect = QRect(rect.left() + 12, rect.center().y() - 22, 44, 44)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(STOCK_CARD_AVATAR_FILL_COLOR))
        painter.drawRoundedRect(avatar_rect, 12, 12)
        painter.setPen(QColor(STOCK_CARD_AVATAR_TEXT_COLOR))
        painter.setFont(QFont(STOCK_CARD_FONT_FAMILY, STOCK_CARD_AVATAR_FONT_SIZE, QFont.Weight.Bold))
        initial = (str(title).strip()[:1] or "#").upper()
        painter.drawText(avatar_rect, Qt.AlignmentFlag.AlignCenter, initial)

        x = avatar_rect.right() + 12
        text_right = hook_rect.left() - 10
        text_width = max(10, text_right - x)

        if badge:
            painter.setFont(QFont(STOCK_CARD_FONT_FAMILY, STOCK_CARD_ACTION_FONT_SIZE, QFont.Weight.Bold))
            fm = painter.fontMetrics()
            badge_w = min(max(58, fm.horizontalAdvance(badge) + 18), max(58, text_width // 2))
            badge_h = 22
            badge_rect = QRect(hook_rect.left() - badge_w - 8, rect.top() + 8, badge_w, badge_h)
            if badge_rect.left() > x + 70:
                painter.setPen(QPen(QColor(STOCK_CARD_BADGE_BORDER_COLOR), 1))
                painter.setBrush(QColor(STOCK_CARD_BADGE_FILL_COLOR))
                painter.drawRoundedRect(badge_rect, 11, 11)
                painter.setPen(QColor(STOCK_CARD_BADGE_TEXT_COLOR))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge)
                text_right = badge_rect.left() - 10
                text_width = max(10, text_right - x)

        painter.setPen(QColor(STOCK_CARD_TITLE_COLOR))
        painter.setFont(QFont(STOCK_CARD_FONT_FAMILY, STOCK_CARD_TITLE_FONT_SIZE, QFont.Weight.Bold))
        title_rect = QRect(x, rect.top() + 10, text_width, 20)
        fm = painter.fontMetrics()
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(title, Qt.TextElideMode.ElideRight, title_rect.width()),
        )

        painter.setPen(QColor(STOCK_CARD_BODY_COLOR))
        painter.setFont(QFont(STOCK_CARD_FONT_FAMILY, STOCK_CARD_META_FONT_SIZE))
        sub_rect = QRect(x, title_rect.bottom() + 4, text_width, 18)
        fm = painter.fontMetrics()
        painter.drawText(
            sub_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(subtitle, Qt.TextElideMode.ElideRight, sub_rect.width()),
        )

        painter.setPen(QColor(STOCK_CARD_MUTED_COLOR))
        extra_rect = QRect(x, sub_rect.bottom() + 2, text_width, 18)
        fm = painter.fontMetrics()
        painter.drawText(
            extra_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(extra, Qt.TextElideMode.ElideRight, extra_rect.width()),
        )


class ManagerCardsListWidget(QListView):
    selection_changed = pyqtSignal()
    page_changed = pyqtSignal(int, int, int, int)
    record_selected = pyqtSignal(object)
    record_clicked = pyqtSignal(object)
    selection_button_clicked = pyqtSignal(object, bool)
    bulk_selection_changed = pyqtSignal(int)
    selection_state_changed = pyqtSignal()
    background_clicked = pyqtSignal()
    blank_area_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setMouseTracking(True)
        self.setSpacing(6)
        self.setUniformItemSizes(False)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self._hook_click_handled = False
        self._active_spin_allowed: bool = True
        self._active_border_animation_enabled: bool = False
        self._guide_select_animation_enabled: bool = False
        self._external_selection_handler_enabled: bool = False
        self._last_selection_signature: tuple[str, ...] = tuple()
        self._all_records: list[dict[str, Any]] = []
        self._page_records: list[dict[str, Any]] = []
        self._active_record_id: Optional[int] = None
        self._pre_click_active_record_id: Optional[int] = None
        self._has_pre_click_active_snapshot: bool = False
        self._bulk_selected_ids: set[int] = set()
        self._pagination_enabled: bool = False
        self.page_size: int = 20
        self.current_page: int = 1

        self._model = ManagerCardsListModel(parent=self, on_selection_changed=self._emit_selected)
        self._delegate = ManagerCardsListDelegate(self, on_select_button=self._on_select_button_clicked)
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self.clicked.connect(self._on_clicked)

        self._active_border_timer = QTimer(self)
        self._active_border_timer.setInterval(42)
        self._active_border_timer.timeout.connect(self._tick_active_border_animation)

    def _mark_hook_click_handled(self) -> None:
        self._hook_click_handled = True

    def _on_select_button_clicked(self, index: QModelIndex, selected: bool) -> bool:
        if not index.isValid():
            return False
        if bool(index.data(ManagerCardsListModel.PlaceholderRole)):
            return False
        rec = index.data(ManagerCardsListModel.RecordRole)
        if not self._external_selection_handler_enabled:
            self.set_record_selected(rec, bool(selected))
        self.selection_button_clicked.emit(rec, bool(selected))
        return True

    def _on_clicked(self, index: QModelIndex) -> None:
        if self._hook_click_handled:
            self._hook_click_handled = False
            return
        if not index.isValid():
            return
        if bool(index.data(ManagerCardsListModel.PlaceholderRole)):
            self.background_clicked.emit()
            self.blank_area_clicked.emit()
            return
        rec = index.data(ManagerCardsListModel.RecordRole)
        self._pre_click_active_record_id = self._safe_record_id(self._active_record_id)
        self._has_pre_click_active_snapshot = True
        self.set_selected_id(_manager_record_id(rec))
        self.record_clicked.emit(rec)

    def mousePressEvent(self, event):
        try:
            pos = event.position().toPoint()
            idx = self.indexAt(pos)
            if not idx.isValid():
                self.background_clicked.emit()
                self.blank_area_clicked.emit()
        except Exception:
            pass
        super().mousePressEvent(event)

    def _selection_signature(self) -> tuple[str, ...]:
        return tuple(sorted(str(record_id) for record_id in self.bulk_selected_ids()))

    def _emit_selection_state_if_needed(self, *, force: bool = False) -> None:
        signature = self._selection_signature()
        if not force and signature == self._last_selection_signature:
            return
        self._last_selection_signature = signature
        self.selection_state_changed.emit()

    def _emit_selected(self) -> None:
        active_row = self._model.active_row()
        self._set_active_border_animation_enabled(active_row >= 0 and self._active_spin_allowed)
        self.record_selected.emit(self.selected_record())
        self._emit_selection_state_if_needed()
        self.selection_changed.emit()
        self.bulk_selection_changed.emit(self._model.bulk_selected_count())
        self.page_changed.emit(self.current_page, self.get_total_pages(), self.total_record_count(), self.shown_count())

    @staticmethod
    def _safe_record_id(value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    def set_pagination_enabled(self, enabled: bool) -> None:
        self._pagination_enabled = bool(enabled)
        self.current_page = 1
        self._rebuild_page()

    def set_items(
        self,
        records: list[dict[str, Any]],
        *,
        keep_selected_id: Optional[int] = None,
        keep_bulk_selected_ids: Optional[list[int]] = None,
    ) -> None:
        selected_id = keep_selected_id if keep_selected_id is not None else self.selected_record_id()
        bulk_ids = keep_bulk_selected_ids if keep_bulk_selected_ids is not None else self.bulk_selected_ids()
        self._all_records = list(records or [])
        self._active_record_id = self._safe_record_id(selected_id)
        self._bulk_selected_ids = {
            rid
            for rid in (self._safe_record_id(v) for v in (bulk_ids or []))
            if rid is not None
        }
        self._rebuild_page()

    def set_selected_id(self, record_id: Optional[int]) -> bool:
        rid = self._safe_record_id(record_id)
        self._active_record_id = rid
        ok = self._reapply_active_row()
        self._emit_selected()
        return ok

    def set_external_selection_handler_enabled(self, enabled: bool) -> None:
        self._external_selection_handler_enabled = bool(enabled)

    def set_record_selected(self, record: Optional[dict[str, Any]], selected: bool) -> None:
        record_id = self._safe_record_id(_manager_record_id(record))
        if record_id is None or record_id == 0:
            return
        if selected:
            self._bulk_selected_ids.add(record_id)
        else:
            self._bulk_selected_ids.discard(record_id)
        self._reapply_bulk_rows()
        self._emit_selected()

    def selected_record(self) -> Optional[dict[str, Any]]:
        rid = self._safe_record_id(self._active_record_id)
        if rid is None:
            return None
        for rec in self._all_records:
            if self._safe_record_id(_manager_record_id(rec)) == rid:
                return rec
        return None

    def selected_record_id(self) -> Optional[int]:
        return self._safe_record_id(self._active_record_id)

    def is_active_record(self, record) -> bool:
        record_id = self._safe_record_id(_manager_record_id(record))
        return record_id is not None and record_id == self._safe_record_id(self._active_record_id)

    def take_pre_click_active_match(self, record):
        if not self._has_pre_click_active_snapshot:
            return None
        self._has_pre_click_active_snapshot = False
        previous_id = self._safe_record_id(self._pre_click_active_record_id)
        self._pre_click_active_record_id = None
        record_id = self._safe_record_id(_manager_record_id(record))
        return record_id is not None and previous_id is not None and record_id == previous_id

    def clear_active_selection(self) -> None:
        self._active_record_id = None
        self._model.clear_active_row()
        self._emit_selected()

    def clear_bulk_selection(self) -> None:
        self._bulk_selected_ids.clear()
        self._model.clear_bulk_selected_rows()
        self._emit_selected()

    def bulk_selected_records(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for rec in self._all_records:
            rid = self._safe_record_id(_manager_record_id(rec))
            if rid is not None and rid in self._bulk_selected_ids:
                out.append(rec)
        return out

    def bulk_selected_ids(self) -> list[int]:
        return sorted(self._bulk_selected_ids)

    def bulk_selected_count(self) -> int:
        return len(self._bulk_selected_ids)

    def shown_count(self) -> int:
        return len(self._page_records)

    def get_selected_records(self) -> list[dict[str, Any]]:
        return self.bulk_selected_records()

    def total_record_count(self) -> int:
        return len(self._all_records)

    def get_total_pages(self) -> int:
        total = self.total_record_count()
        if total <= 0:
            return 1
        if not self._pagination_enabled:
            return 1
        return max(1, (total + self.page_size - 1) // self.page_size)

    def set_page_size(self, size: int) -> None:
        value = max(1, int(size or 20))
        self.page_size = value
        self.current_page = 1
        self._rebuild_page()

    def go_to_page(self, page: int) -> None:
        self.current_page = max(1, min(int(page or 1), self.get_total_pages()))
        self._rebuild_page()

    def next_page(self) -> None:
        self.go_to_page(self.current_page + 1)

    def prev_page(self) -> None:
        self.go_to_page(self.current_page - 1)

    def clear_selected_records(self) -> None:
        self.clear_bulk_selection()

    def select_all_filtered_records(self) -> None:
        self._bulk_selected_ids = {
            rid
            for rid in (self._safe_record_id(_manager_record_id(rec)) for rec in self._all_records)
            if rid is not None
        }
        self._reapply_bulk_rows()
        self._emit_selected()

    def _reapply_active_row(self) -> bool:
        rid = self._safe_record_id(self._active_record_id)
        if rid is None:
            self._model.clear_active_row()
            return False
        ok = self._model.set_selected_by_id(rid)
        if not ok:
            self._model.clear_active_row()
        return ok

    def _reapply_bulk_rows(self) -> None:
        self._model.clear_bulk_selected_rows()
        for row in range(self._model.rowCount()):
            idx = self._model.index(row)
            rec = idx.data(ManagerCardsListModel.RecordRole)
            rid = self._safe_record_id(_manager_record_id(rec))
            if rid is not None and rid in self._bulk_selected_ids:
                self._model.set_bulk_selected_row(row, True)

    def _rebuild_page(self) -> None:
        total_pages = self.get_total_pages()
        self.current_page = max(1, min(self.current_page, total_pages))
        if not self._pagination_enabled:
            self._page_records = list(self._all_records)
        else:
            start = (self.current_page - 1) * self.page_size
            end = start + self.page_size
            self._page_records = list(self._all_records[start:end])
        self._model.set_items(
            self._page_records,
            selected_id=self._active_record_id,
            bulk_selected_ids=list(self._bulk_selected_ids),
        )
        self._emit_selected()

    def set_active_spin_allowed(self, allowed: bool) -> None:
        self._active_spin_allowed = bool(allowed)
        self._delegate.set_active_visual_enabled(self._active_spin_allowed)
        self._set_active_border_animation_enabled(self._model.active_row() >= 0 and self._active_spin_allowed)

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self._guide_select_animation_enabled = bool(enabled)
        self._delegate.set_guide_select_enabled(self._guide_select_animation_enabled)
        self._sync_border_animation_timer()

    def _set_active_border_animation_enabled(self, enabled: bool) -> None:
        self._active_border_animation_enabled = bool(enabled)
        self._sync_border_animation_timer()

    def _sync_border_animation_timer(self) -> None:
        should_tick = self._active_border_animation_enabled or self._guide_select_animation_enabled
        if should_tick:
            if not self._active_border_timer.isActive():
                self._active_border_timer.start()
        elif self._active_border_timer.isActive():
            self._active_border_timer.stop()

        if not self._active_border_animation_enabled:
            self._delegate.reset_spin_phase()
        if not self._guide_select_animation_enabled:
            self._delegate.reset_guide_phase()
        self._update_animation_rows()

    def _tick_active_border_animation(self) -> None:
        if self._active_border_animation_enabled:
            self._delegate.advance_spin_phase(1.35)
        if self._guide_select_animation_enabled:
            self._delegate.advance_guide_phase(1.35)
        self._update_animation_rows()

    def _update_animation_rows(self) -> None:
        if self._guide_select_animation_enabled:
            self.viewport().update()
            return
        active_row = self._model.active_row()
        if active_row < 0:
            return
        index = self._model.index(active_row)
        rect = self.visualRect(index)
        if rect.isValid() and not rect.isNull():
            self.viewport().update(rect.adjusted(-2, -2, 2, 2))
        else:
            self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_dynamic_row_width()

    def sync_dynamic_row_width(self) -> None:
        try:
            self.doItemsLayout()
            self.viewport().update()
        except Exception:
            return


# =========================================================
# ? Base Fullscreen Dialog (MessageBox Ghost Fix)
# =========================================================

class StockManagerWorkspaceBehaviorAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(
        self,
        dialog,
        *,
        list_widget_attr: str,
        edit_message: str,
        bulk_message: str,
    ) -> None:
        self.dialog = dialog
        self._list_widget_attr = list_widget_attr
        self._edit_message = edit_message
        self._bulk_message = bulk_message

    @property
    def list_widget(self):
        return self.dialog.__getattribute__(self._list_widget_attr)

    def get_mode(self) -> str:
        return str(self.dialog._left_mode or "edit")

    def set_mode(self, mode: str) -> None:
        self.dialog._set_left_mode(mode)

    def get_active_key(self) -> str:
        return str(self.list_widget.selected_record_id() or "")

    def get_selected_count(self) -> int:
        return int(self.list_widget.bulk_selected_count() or 0)

    def get_record_key(self, record) -> str:
        return str(_manager_record_id(record) or "")

    def prepare_new(self) -> None:
        self.dialog._prepare_manager_workspace_new()

    def activate_record(self, record) -> None:
        self.list_widget.set_selected_id(_manager_record_id(record))

    def clear_active(self) -> None:
        self.list_widget.clear_active_selection()
        self.dialog._clear_manager_workspace_state()

    def apply_selection(self, record, selected: bool) -> None:
        self.list_widget.set_record_selected(record, bool(selected))

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self.list_widget.set_select_button_guide_enabled(bool(enabled))

    def on_state_changed(self) -> None:
        self.dialog._sync_manager_workspace_state()

    def edit_guidance_message(self) -> str:
        return self._edit_message

    def bulk_guidance_message(self) -> str:
        return self._bulk_message

class CompanyManagerDialog(FullscreenDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Firmalar")
        self._left_mode = "edit"
        self._records: list[dict[str, Any]] = []
        self._has_loaded_once = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)
        outer.addLayout(content_row, 1)

        self._workspace = RecordWorkspaceScaffold(
            self,
            left_title=STOCK_MANAGER_LEFT_EDIT_TITLE,
            left_subtitle="Düzenlemek için sağdaki listeden bir firma seç.",
            filters_title=STOCK_MANAGER_FILTERS_TITLE,
            records_title="Firma Listesi",
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
            style_sheet=None,
            shell_kwargs=STOCK_MANAGER_WORKSPACE_SHELL_KWARGS,
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": "Yeni firma paneli",
                    "icon_path": str(ASSETS_DIR / "yeni-kayit.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": "Firma düzenleme paneli",
                    "icon_path": str(ASSETS_DIR / "duzenleme-icon.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "bulk",
                    "text": "",
                    "tooltip": STOCK_MANAGER_SIDEBAR_BULK_TOOLTIP,
                    "icon_path": str(ASSETS_DIR / "toplu-secim (2).png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
            ),
        )
        content_row.addWidget(self._workspace, 1)

        self._workspace_shell = self._workspace.shell
        self._panel_sidebar = self._workspace.sidebar
        splitter = self._workspace_shell.splitter
        splitter.setChildrenCollapsible(True)
        splitter.setHandleWidth(6)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        self._manager_splitter = splitter
        self._left_stick_size = 520
        self._left_card = self._workspace.left_card
        self.left_panel_title = self._workspace.left_card.title_label
        self.left_panel_hint = self._workspace.left_card.subtitle_label
        self._editor_scroll = self._workspace.editor_scroll
        self._editor_actions_wrap = self._workspace.editor_actions_host
        self.bulk_panel = self._workspace.bulk_panel
        editor_host = QWidget(self._workspace.editor_host)
        editor_host.setObjectName("FormBody")
        editor_layout = QVBoxLayout(editor_host)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(10)
        self._editor_host = editor_host
        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self.le_pk = QLineEdit(); self.le_pk.setEnabled(False); self.le_pk.hide()
        self.le_name = QLineEdit(); self.le_name.setPlaceholderText("Örn: ABC Tedarik")
        self.le_tax = QLineEdit(); self.le_tax.setPlaceholderText("Vergi No (ops.)")
        self.le_phone = PhoneNumberInput(
            dial_codes=list(PHONE_DIAL_CODE_OPTIONS or []),
            default_code="+90",
            number_placeholder="5000000000",
        )
        self.le_email = QLineEdit(); self.le_email.setPlaceholderText("E-posta (ops.)")
        self.le_address = QLineEdit(); self.le_address.setPlaceholderText("Adres (ops.)")
        self.le_note = QLineEdit(); self.le_note.setPlaceholderText("Not (ops.)")

        form.addRow("Şirket Adı", self.le_name)
        form.addRow("Vergi No", self.le_tax)
        form.addRow("Telefon", self.le_phone)
        form.addRow("E-posta", self.le_email)
        form.addRow("Adres", self.le_address)
        form.addRow("Not", self.le_note)
        editor_layout.addLayout(form)

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text=STOCK_MANAGER_CLEAR_TEXT,
            save_new_text="Firma Kaydet",
            save_edit_text=STOCK_MANAGER_SAVE_EDIT_TEXT,
            delete_text=STOCK_MANAGER_DELETE_TEXT,
        )
        self.btn_clear = self._workspace.editor_action_bar.clear_button
        self.btn_save = self._workspace.editor_action_bar.save_button
        self.btn_delete = self._workspace.editor_action_bar.delete_button

        self._workspace.editor_action_bar.clearRequested.connect(self.clear_form)
        self._workspace.editor_action_bar.saveRequested.connect(self.save_or_update)
        self._workspace.editor_action_bar.deleteRequested.connect(self.delete_company)

        bulk_content = QWidget(self.bulk_panel)
        bulk_layout = QVBoxLayout(bulk_content)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.setSpacing(8)
        bulk_layout.setContentsMargins(10, 8, 10, 8)
        bulk_layout.addWidget(QLabel(STOCK_MANAGER_BULK_TITLE, objectName="Section"))
        self.bulk_summary = QLabel("Seçili firma: 0", objectName="SubTitle")
        self.bulk_summary.setWordWrap(True)
        bulk_hint = QLabel("Seçilen firmalar üzerinde toplu silme işlemi yapabilirsin.", objectName="SubTitle")
        bulk_hint.setWordWrap(True)
        self.btn_bulk_delete = _btn(STOCK_MANAGER_BULK_DELETE_TEXT, "Danger", 42)
        self.btn_bulk_clear = _btn(STOCK_MANAGER_BULK_CLEAR_TEXT, "Ghost", 42)
        self.btn_bulk_delete.clicked.connect(self._bulk_delete_selected)
        self.btn_bulk_clear.clicked.connect(self._clear_bulk_selection)
        bulk_layout.addWidget(self.bulk_summary)
        bulk_layout.addWidget(bulk_hint)
        bulk_layout.addWidget(self.btn_bulk_delete)
        bulk_layout.addWidget(self.btn_bulk_clear)
        bulk_layout.addStretch(1)
        self.bulk_panel.hide()

        filters_host = QWidget(self._workspace.filters_host)
        flt = QVBoxLayout(filters_host)
        flt.setContentsMargins(0, 0, 0, 0)
        flt.setSpacing(8)
        row_top = QHBoxLayout()
        row_top.setSpacing(8)
        self.le_filter_search = QLineEdit()
        self.le_filter_search.setObjectName("Search")
        self.le_filter_search.setPlaceholderText("Genel Ara (firma, vergi no, telefon, e-posta, adres...)")
        self.btn_reset_filters = _btn(STOCK_MANAGER_RESET_FILTERS_TEXT, "SoftDanger", 40)
        row_top.addWidget(self.le_filter_search, 1)
        row_top.addWidget(self.btn_reset_filters, 0)
        row_filters = QHBoxLayout()
        row_filters.setSpacing(8)
        self.cb_filter_tax = SwitchSelectWidget(title="Vergi No", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_tax.addItem("Var", "has")
        self.cb_filter_tax.addItem("Yok", "none")
        row_filters.addWidget(self.cb_filter_tax, 1)
        row_filters.addStretch(1)
        flt.addLayout(row_top)
        flt.addLayout(row_filters)
        self.records_list = ManagerCardsListWidget()
        self.records_list.record_selected.connect(self.on_select)
        self.records_list.bulk_selection_changed.connect(self._on_record_bulk_selection_changed)
        self.le_filter_search.textChanged.connect(self._apply_list_filters)
        self.cb_filter_tax.currentIndexChanged.connect(self._apply_list_filters)
        self.btn_reset_filters.clicked.connect(self._reset_list_filters)
        self._workspace.set_editor_widget(editor_host)
        self._workspace.set_bulk_widget(bulk_content)
        self._workspace.set_filters_widget(filters_host)
        self._workspace.set_list_widget(self.records_list)
        self._workspace.footer_bar.setObjectName("BottomBar")
        self._workspace.footer_bar.page_size_label.setText("Sayfa başına")
        splitter.setSizes([0, 1420])

        self._workspace_adapter = StockManagerWorkspaceBehaviorAdapter(
            self,
            list_widget_attr="records_list",
            edit_message="Düzenlemek için sağdaki listeden bir firma seç.",
            bulk_message="Toplu işlem için sağdaki listeden en az bir firmayı SEÇ ile işaretle.",
        )
        self._workspace_behavior = self._workspace.create_behavior_controller(
            adapter=self._workspace_adapter,
        )

        self._set_left_mode("edit")
        self._update_bulk_panel_state()
        self._sync_guidance_overlays_geometry()
        self._sync_focus_guidance_state()
        self._sync_sidebar_state_from_splitter()
        _apply_stock_composite_theme(self)

    def showEvent(self, event):
        super().showEvent(event)
        if self._has_loaded_once:
            return
        self._has_loaded_once = True
        self._set_list_loading(True)
        QTimer.singleShot(0, self.refresh)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.records_list.sync_dynamic_row_width()
        self._sync_guidance_overlays_geometry()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def _refresh_left_panel_header(self):
        mode = str(self._left_mode or "edit").lower()
        if mode == "new":
            self.left_panel_title.setText(STOCK_MANAGER_LEFT_NEW_TITLE)
            self.left_panel_hint.setText("Yeni firma bilgilerini doldurup kaydet.")
            return
        if mode == "bulk":
            self.left_panel_title.setText(STOCK_MANAGER_LEFT_BULK_TITLE)
            self.left_panel_hint.setText("Seçili firmalar için toplu işlemleri buradan yönet.")
            return
        self.left_panel_title.setText(STOCK_MANAGER_LEFT_EDIT_TITLE)
        rec = self._primary_selected_record()
        if rec is None:
            self.left_panel_hint.setText("Düzenlemek için sağdaki listeden bir firma seç.")
            return
        self.left_panel_hint.setText(f"Seçili firma: {str(rec.get('name') or '-').strip()}")

    def _set_left_mode(self, mode: str):
        mode_key = str(mode or "").lower()
        if mode_key not in {"new", "edit", "bulk"}:
            mode_key = "edit"
        self._left_mode = mode_key
        self._workspace.set_editor_action_mode(mode_key)
        show_editor = self._left_mode in {"new", "edit"}
        self._editor_scroll.setVisible(show_editor)
        self._editor_host.setVisible(show_editor)
        self.bulk_panel.setVisible(not show_editor)
        self._update_bulk_panel_state()
        self._refresh_left_panel_header()
        self._sync_sidebar_state_from_splitter()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def _reset_list_filters(self):
        self.le_filter_search.clear()
        self.cb_filter_tax.setCurrentText("Tümü")
        self._apply_list_filters()

    def _apply_list_filters(
        self,
        *_args,
        keep_selected_id: Optional[int] = None,
        keep_bulk_selected_ids: Optional[list[int]] = None,
    ):
        rows = list(self._records)

        tax_filter = self.cb_filter_tax.currentData()
        if tax_filter == "has":
            rows = [r for r in rows if str(r.get("tax_no") or "").strip()]
        elif tax_filter == "none":
            rows = [r for r in rows if not str(r.get("tax_no") or "").strip()]

        q = (self.le_filter_search.text() or "").strip().casefold()
        if q:
            def _hit(value: Any) -> bool:
                return q in str(value or "").casefold()

            rows = [
                r for r in rows
                if _hit(r.get("name"))
                or _hit(r.get("tax_no"))
                or _hit(r.get("phone"))
                or _hit(r.get("email"))
                or _hit(r.get("address"))
                or _hit(r.get("note"))
            ]

        active_id = keep_selected_id if keep_selected_id is not None else self.records_list.selected_record_id()
        bulk_ids = keep_bulk_selected_ids if keep_bulk_selected_ids is not None else self.records_list.bulk_selected_ids()
        self.records_list.set_items(rows, keep_selected_id=active_id, keep_bulk_selected_ids=bulk_ids)
        self._update_bulk_panel_state()
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def _selected_rows(self) -> list[int]:
        return list(range(self.records_list.bulk_selected_count()))

    def _selected_ids(self) -> list[int]:
        return self.records_list.bulk_selected_ids()

    def _selected_records(self) -> list[dict[str, Any]]:
        return self.records_list.bulk_selected_records()

    def _primary_selected_record(self) -> Optional[dict[str, Any]]:
        selected = self.records_list.selected_record()
        if selected is not None:
            return selected
        bulk = self.records_list.bulk_selected_records()
        return bulk[0] if bulk else None

    def _prepare_manager_workspace_new(self):
        self.records_list.clear_active_selection()
        self.clear_form(clear_table_selection=False)
        self._set_left_mode("new")

    def _clear_manager_workspace_state(self):
        self.clear_form(clear_table_selection=False)

    def _sync_manager_workspace_state(self):
        self._update_bulk_panel_state()
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def _sync_workspace_summary(self) -> None:
        self._workspace.set_records_summary_text(f"{self.records_list.shown_count()} / {len(self._records)} kayıt")

    def _select_record_by_id(self, pk: int):
        self.records_list.set_selected_id(pk)

    def _update_bulk_panel_state(self):
        count = self.records_list.bulk_selected_count()
        self.bulk_summary.setText(f"Seçili firma: {count}")
        self.btn_bulk_delete.setEnabled(count > 0)
        self._sync_workspace_summary()

    def _clear_bulk_selection(self):
        self.records_list.clear_bulk_selection()
        self._update_bulk_panel_state()
        if self._left_mode == "bulk" and self._is_editor_panel_open():
            self._close_editor_panel()
        else:
            self._sync_sidebar_state_from_splitter()

    def _bulk_delete_selected(self):
        records = self._selected_records()
        if not records:
            self.error("Hata", "Toplu silme için en az bir firma seç.")
            return
        if not self.confirm("Silme Onay", f"{len(records)} firma silinecek. Emin misin?"):
            return
        success = 0
        failed = 0
        failures: list[str] = []
        for rec in records:
            try:
                pk = int(rec.get("id"))
            except Exception:
                failed += 1
                continue
            res = action_delete_company(pk=pk)
            if res.success:
                success += 1
            else:
                failed += 1
                failures.append(f"{pk}: {res.message}")
        self.refresh()
        if failed <= 0:
            self.info("OK", f"{success} firma silindi.")
            self._close_editor_panel()
            return
        self.error(
            "Kısmi Başarı",
            f"{success} firma silindi, {failed} firma silinemedi."
            + (f"\n{chr(10).join(failures[:5])}" if failures else ""),
        )

    def _sync_guidance_overlays_geometry(self):
        self._workspace.sync_list_loading_geometry()
        self._workspace_shell.sync_guidance_geometry()

    def _sync_focus_guidance_state(self):
        panel_open = self._is_editor_panel_open()
        selected = self.records_list.selected_record()
        bulk_count = self.records_list.bulk_selected_count()
        bulk_mode = self._left_mode == "bulk" and panel_open
        self.records_list.set_select_button_guide_enabled(bulk_mode and bulk_count <= 0)
        self.records_list.set_active_spin_allowed(self._left_mode == "edit" and panel_open and selected is not None)

    def _update_edit_lock_state(self):
        return

    def _on_record_bulk_selection_changed(self, _count: int):
        self._update_bulk_panel_state()
        if self._left_mode == "bulk" and self._is_editor_panel_open() and self.records_list.bulk_selected_count() <= 0:
            self._close_editor_panel()
            return
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def _is_editor_panel_open(self) -> bool:
        return self._workspace_shell.is_left_panel_open()

    def _sync_sidebar_state_from_splitter(self):
        self._workspace.sync_list_loading_geometry()
        self._workspace_shell.sync_guidance_geometry()
        self._workspace_behavior.sync_state()
        self.records_list.sync_dynamic_row_width()

    def _open_editor_panel(self):
        self._workspace_shell.open_left_panel(min_left=320, min_right=320)
        self._sync_sidebar_state_from_splitter()

    def _close_editor_panel(self):
        if self._left_mode == "edit":
            self.records_list.clear_active_selection()
            self.clear_form(clear_table_selection=False)
        self._workspace_shell.close_left_panel()
        self._sync_sidebar_state_from_splitter()

    def _open_new_form(self):
        self.clear_form(clear_table_selection=True)
        self._set_left_mode("new")
        self._open_editor_panel()

    def clear_form(self, *, clear_table_selection: bool = True):
        self.le_pk.clear()
        self.le_name.clear()
        self.le_tax.clear()
        self.le_phone.clear()
        self.le_email.clear()
        self.le_address.clear()
        self.le_note.clear()
        if clear_table_selection:
            self.records_list.clear_active_selection()
            self.records_list.clear_bulk_selection()
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def _set_list_loading(self, busy: bool, message: str = "Firmalar yükleniyor...") -> None:
        self._workspace.set_list_loading(bool(busy), message=message)

    def refresh(self):
        self._set_list_loading(True)
        try:
            keep_selected_id = self.records_list.selected_record_id()
            keep_bulk_ids = self.records_list.bulk_selected_ids()
            res = action_list_companies()
            self._records = []
            if not res.success:
                self.records_list.set_items([], keep_selected_id=None, keep_bulk_selected_ids=keep_bulk_ids)
                self.clear_form(clear_table_selection=False)
                self._update_bulk_panel_state()
                self._refresh_left_panel_header()
                self._sync_focus_guidance_state()
                self._update_edit_lock_state()
                self.error("Hata", res.message)
                return

            records = res.data.get("records", []) or []
            for c in records:
                rec = {
                    "pk": getattr(c, "pk", None),
                    "name": getattr(c, "name", "") or "",
                    "tax_no": getattr(c, "tax_no", "") or "",
                    "phone": getattr(c, "phone", "") or "",
                    "email": getattr(c, "email", "") or "",
                    "address": getattr(c, "address", "") or "",
                    "note": getattr(c, "note", "") or "",
                }
                rec["title"] = str(rec.get("name") or "-")
                rec["subtitle"] = f"Vergi No: {str(rec.get('tax_no') or '-')} • Telefon: {str(rec.get('phone') or '-')}"
                rec["extra"] = f"E-posta: {str(rec.get('email') or '-')} • Adres: {str(rec.get('address') or '-')}"
                rec["badge"] = "Firma"
                self._records.append(rec)
            self._apply_list_filters(keep_selected_id=keep_selected_id, keep_bulk_selected_ids=keep_bulk_ids)
        finally:
            self._set_list_loading(False)

    def on_select(self, rec: Optional[dict[str, Any]] = None):
        if self._left_mode == "bulk":
            self._update_bulk_panel_state()
            if self._is_editor_panel_open() and self.records_list.bulk_selected_count() <= 0:
                self._close_editor_panel()
                return
            self._refresh_left_panel_header()
            self._sync_focus_guidance_state()
            self._update_edit_lock_state()
            return
        if rec is None:
            rec = self._primary_selected_record()
        if rec is None:
            if self._left_mode == "edit":
                self.clear_form(clear_table_selection=False)
            self._refresh_left_panel_header()
            self._sync_focus_guidance_state()
            self._update_edit_lock_state()
            return
        if self._left_mode != "edit":
            self._set_left_mode("edit")
        self.le_pk.setText(str(rec.get("pk") or ""))
        self.le_name.setText(str(rec.get("name") or ""))
        self.le_tax.setText(str(rec.get("tax_no") or ""))
        self.le_phone.setText(str(rec.get("phone") or ""))
        self.le_email.setText(str(rec.get("email") or ""))
        self.le_address.setText(str(rec.get("address") or ""))
        self.le_note.setText(str(rec.get("note") or ""))
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def save_or_update(self):
        name = (self.le_name.text() or "").strip()
        if not name:
            self.error("Hata", "Şirket adı boş olamaz.")
            return

        pk_txt = (self.le_pk.text() or "").strip()
        payload = {
            "name": name,
            "tax_no": (self.le_tax.text() or "").strip() or None,
            "phone": (self.le_phone.text() or "").strip() or None,
            "email": (self.le_email.text() or "").strip() or None,
            "address": (self.le_address.text() or "").strip() or None,
            "note": (self.le_note.text() or "").strip() or None,
        }

        res = action_update_company(pk=int(pk_txt), update_data=payload) if pk_txt else action_create_company(**payload)
        if res.success:
            self.info("OK", res.message or "İşlem bağarılı.")
            self.refresh()
            self._open_new_form()
        else:
            self.error("Hata", f"{res.message}\n{res.data}")

    def delete_company(self):
        pk_txt = (self.le_pk.text() or "").strip()
        if not pk_txt:
            self.error("Hata", "Silmek için listeden bir firma seç.")
            return
        if not self.confirm("Silme Onay", "Bu firma silinecek. Emin misin?"):
            return
        res = action_delete_company(pk=int(pk_txt))
        if res.success:
            self.info("OK", res.message or "Silindi.")
            self.refresh()
            self.clear_form(clear_table_selection=True)
        else:
            self.error("Hata", f"{res.message}\n{res.data}")

    def _primary_selected_record(self) -> Optional[dict[str, Any]]:
        selected = self.records_list.selected_record()
        if selected is not None:
            return selected
        bulk = self.records_list.bulk_selected_records()
        return bulk[0] if bulk else None

    def _selected_rows(self) -> list[int]:
        return list(range(self.records_list.bulk_selected_count()))

    def _selected_ids(self) -> list[int]:
        return self.records_list.bulk_selected_ids()

    def _selected_records(self) -> list[dict[str, Any]]:
        return self.records_list.bulk_selected_records()

    def _select_record_by_id(self, pk: int):
        self.records_list.set_selected_id(pk)

    def _update_bulk_panel_state(self):
        count = self.records_list.bulk_selected_count()
        self.bulk_summary.setText(f"Seçili firma: {count}")
        self.btn_bulk_delete.setEnabled(count > 0)

    def _clear_bulk_selection(self):
        self.records_list.clear_bulk_selection()
        self._update_bulk_panel_state()
        if self._left_mode == "bulk" and self._is_editor_panel_open():
            self._close_editor_panel()
        else:
            self._sync_sidebar_state_from_splitter()

    def _bulk_delete_selected(self):
        records = self._selected_records()
        if not records:
            self.error("Hata", "Toplu silme için en az bir firma seç.")
            return
        if not self.confirm("Silme Onay", f"{len(records)} firma silinecek. Emin misin?"):
            return
        success = 0
        failed = 0
        failures: list[str] = []
        for rec in records:
            try:
                pk = int(rec.get("pk"))
            except Exception:
                failed += 1
                continue
            res = action_delete_company(pk=pk)
            if res.success:
                success += 1
            else:
                failed += 1
                failures.append(f"{pk}: {res.message}")
        self.refresh()
        if failed <= 0:
            self.info("OK", f"{success} firma silindi.")
            self._close_editor_panel()
            return
        self.error(
            "Kısmi Bağarı",
            f"{success} firma silindi, {failed} firma silinemedi."
            + (f"\n{chr(10).join(failures[:5])}" if failures else ""),
        )

# =========================================================
# ? Stock Tx Dialog
# =========================================================








