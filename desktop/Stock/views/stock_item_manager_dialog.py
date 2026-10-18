from __future__ import annotations
from .views import *

def _stock_item_record_id(record: Any) -> Optional[int]:
    if isinstance(record, dict):
        value = record.get("id")
        if value in (None, ""):
            value = record.get("pk")
    else:
        value = getattr(record, "id", None)
        if value in (None, ""):
            value = getattr(record, "pk", None)
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed != 0 else None


def _stock_item_unit_desi(record: dict[str, Any] | None) -> Optional[float]:
    if not isinstance(record, dict):
        return None

    candidates: list[float] = []

    try:
        weight = float(record.get("weight_kg"))
    except Exception:
        weight = 0.0
    if weight > 0:
        candidates.append(weight)

    try:
        length = float(record.get("length_cm"))
        width = float(record.get("width_cm"))
        height = float(record.get("height_cm"))
    except Exception:
        length = width = height = 0.0
    if length > 0 and width > 0 and height > 0:
        volumetric = (length * width * height) / 3000.0
        if volumetric > 0:
            candidates.append(volumetric)

    if not candidates:
        return None
    return max(candidates)


def _stock_card_inline_geometry(
    *,
    row_rect: QRect,
    text_left: int,
    anchor_left: int,
) -> dict[str, Any]:
    metric_h = 76
    min_text_w = 300
    min_stock_w = 150
    min_avg_w = 136

    right_edge = int(anchor_left) - 10
    available_for_inline = right_edge - int(text_left) - min_text_w
    min_inline_w = min_stock_w + STOCK_CARD_INLINE_GAP + min_avg_w
    if available_for_inline < min_inline_w:
        return {
            "visible": False,
            "text_right": right_edge,
            "stock_rect": QRect(),
            "avg_rect": QRect(),
        }

    inline_w = min(
        STOCK_CARD_INLINE_STOCK_W + STOCK_CARD_INLINE_GAP + STOCK_CARD_INLINE_AVG_W,
        available_for_inline,
    )
    stock_w = min(STOCK_CARD_INLINE_STOCK_W, max(min_stock_w, int(inline_w * 0.54)))
    avg_w = max(min_avg_w, inline_w - stock_w - STOCK_CARD_INLINE_GAP)
    if avg_w > STOCK_CARD_INLINE_AVG_W:
        avg_w = STOCK_CARD_INLINE_AVG_W
        stock_w = max(min_stock_w, inline_w - avg_w - STOCK_CARD_INLINE_GAP)

    stock_rect = QRect(
        right_edge - stock_w,
        row_rect.center().y() - STOCK_CARD_INLINE_STOCK_H // 2,
        stock_w,
        STOCK_CARD_INLINE_STOCK_H,
    )
    avg_rect = QRect(
        stock_rect.left() - STOCK_CARD_INLINE_GAP - avg_w,
        row_rect.center().y() - metric_h // 2,
        avg_w,
        metric_h,
    )
    return {
        "visible": True,
        "text_right": avg_rect.left() - 10,
        "stock_rect": stock_rect,
        "avg_rect": avg_rect,
    }


class StockItemsListModel(QAbstractListModel):
    TitleRole = Qt.ItemDataRole.UserRole + 1
    SubtitleRole = Qt.ItemDataRole.UserRole + 2
    ExtraRole = Qt.ItemDataRole.UserRole + 3
    IconRole = Qt.ItemDataRole.UserRole + 4
    ItemRole = Qt.ItemDataRole.UserRole + 5
    SelectedRole = Qt.ItemDataRole.UserRole + 6
    PlaceholderRole = Qt.ItemDataRole.UserRole + 7
    ActiveRole = Qt.ItemDataRole.UserRole + 8
    BulkSelectedRole = Qt.ItemDataRole.UserRole + 9

    def __init__(self, items: list[dict] | None = None, parent=None, *, on_selection_changed=None):
        super().__init__(parent)
        self._items: list[dict] = []
        self._has_placeholder = False
        self._on_selection_changed = on_selection_changed
        self._active_row: int = -1
        self._bulk_selected_rows: set[int] = set()
        self._row_by_id: dict[int, int] = {}
        self.set_items(items or [])

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._items):
            return None
        item = self._items[row]

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
        if role == self.IconRole:
            return item.get("icon_path") or ""
        if role == self.ItemRole:
            return item.get("item")
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
    def _safe_item_id(value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    def set_items(
        self,
        items: list[dict],
        *,
        selected_id: Optional[int] = None,
        bulk_selected_ids: Optional[list[int]] = None,
    ):
        keep_selected_id = self._safe_item_id(selected_id)
        keep_bulk_ids = {
            bid for bid in (self._safe_item_id(v) for v in (bulk_selected_ids or []))
            if bid is not None
        }
        self.beginResetModel()
        if items:
            rows: list[dict] = []
            active_row = -1
            bulk_rows: set[int] = set()
            row_by_id: dict[int, int] = {}
            for idx, rec in enumerate(items):
                title = str(rec.get("name") or "-")
                subtitle_parts = [
                    f"SKU: {rec.get('sku') or '-'}",
                    f"Barkod: {rec.get('barcode') or '-'}",
                    f"Tip: {_human_item_type(rec.get('item_type') or '')}",
                    f"Birim: {rec.get('unit') or '-'}",
                ]
                extra_parts = [
                    f"Marka: {rec.get('brand') or '-'}",
                    f"Üst: {rec.get('category') or '-'}",
                    f"Alt: {rec.get('sub_category') or '-'}",
                    f"Stok: {_fmt_num(rec.get('on_hand', 0), default='0')}",
                    f"Durum: {'Aktif' if bool(rec.get('is_active')) else 'Pasif'}",
                ]
                rec_id = self._safe_item_id(_stock_item_record_id(rec))
                if rec_id is not None:
                    row_by_id[rec_id] = idx
                if keep_selected_id is not None and rec_id == keep_selected_id:
                    active_row = idx
                if rec_id is not None and rec_id in keep_bulk_ids:
                    bulk_rows.add(idx)
                rows.append(
                    {
                        "item": rec,
                        "title": title,
                        "subtitle": " | ".join(subtitle_parts),
                        "extra": " | ".join(extra_parts),
                        "icon_path": _first_image_path(rec.get("image_path")),
                    }
                )
            self._items = rows
            self._has_placeholder = False
            self._active_row = active_row
            self._bulk_selected_rows = bulk_rows
            self._row_by_id = row_by_id
        else:
            self._items = [{"placeholder": True, "title": STOCK_ITEMS_EMPTY_TEXT}]
            self._has_placeholder = True
            self._active_row = -1
            self._bulk_selected_rows = set()
            self._row_by_id = {}
        self.endResetModel()

    def item_at(self, row: int) -> dict | None:
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def selected_item(self) -> dict | None:
        if self._has_placeholder or self._active_row < 0 or self._active_row >= len(self._items):
            return None
        return self._items[self._active_row].get("item")

    def selected_item_id(self) -> Optional[int]:
        item = self.selected_item()
        if not item:
            return None
        try:
            return int(_stock_item_record_id(item))
        except Exception:
            return None

    def set_selected(self, row: int, selected: bool) -> None:
        self.set_active_row(row if bool(selected) else -1)

    def set_active_row(self, row: int) -> None:
        if self._has_placeholder:
            row = -1
        if row < 0 or row >= len(self._items):
            row = -1
        elif self._items[row].get("placeholder"):
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

    def set_selected_by_id(self, item_id: Optional[int]) -> bool:
        sid = self._safe_item_id(item_id)
        if sid is None:
            self.clear_active_row()
            return False
        row = self._row_by_id.get(sid)
        if row is not None:
            self.set_active_row(row)
            return True
        self.clear_active_row()
        return False

    def clear_selection(self) -> None:
        self.clear_active_row()

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
        if row < 0 or row >= len(self._items):
            return False
        if self._items[row].get("placeholder"):
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

    def toggle_bulk_selected_row(self, row: int) -> bool:
        return self.set_bulk_selected_row(row, row not in self._bulk_selected_rows)

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

    def bulk_selected_items(self) -> list[dict]:
        out: list[dict] = []
        for row in sorted(self._bulk_selected_rows):
            if 0 <= row < len(self._items):
                item = self._items[row].get("item")
                if isinstance(item, dict):
                    out.append(item)
        return out

    def bulk_selected_ids(self) -> list[int]:
        ids: list[int] = []
        for item in self.bulk_selected_items():
            sid = self._safe_item_id(_stock_item_record_id(item))
            if sid is not None:
                ids.append(sid)
        return ids

    def bulk_selected_count(self) -> int:
        return len(self._bulk_selected_rows)


class StockItemsListDelegate(RecordWorkspaceListDelegate):
    def __init__(self, parent=None, *, on_select_button=None, on_image_click=None, on_source_button=None):
        super().__init__(parent, on_select_button=on_select_button)
        self._row_height = STOCK_MANAGER_CARD_ROW_HEIGHT
        self._hover_source_row: int | None = None
        self._pressed_source_row: int | None = None
        self._on_image_click = on_image_click
        self._on_source_button = on_source_button

    def _is_placeholder_index(self, index: QModelIndex) -> bool:
        return bool(index.data(StockItemsListModel.PlaceholderRole))

    def _is_selected_index(self, index: QModelIndex) -> bool:
        return bool(index.data(StockItemsListModel.BulkSelectedRole))

    def _is_active_index(self, index: QModelIndex) -> bool:
        return bool(index.data(StockItemsListModel.ActiveRole))

    def _is_hook_selected_index(self, index: QModelIndex) -> bool:
        return bool(index.data(StockItemsListModel.BulkSelectedRole))

    def _button_rects(self, rect: QRect, *, has_source: bool, view=None) -> tuple[QRect, Optional[QRect]]:
        left_margin = 8
        source_w = 114
        gap = 8
        select_rect = self._build_hook_rect(
            rect,
            view=view,
            left_margin=left_margin,
            right_margin=10,
        )

        if not has_source:
            return select_rect, None

        source_x = select_rect.left() - gap - source_w
        min_x = rect.left() + left_margin
        if source_x < min_x:
            return select_rect, None
        source_rect = QRect(source_x, select_rect.top(), source_w, select_rect.height())
        return select_rect, source_rect

    def _hook_rect(self, rect: QRect, view=None, *, has_source: bool = False) -> QRect:
        select_rect, _ = self._button_rects(rect, has_source=has_source, view=view)
        return select_rect

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = option.rect.adjusted(6, 4, -6, -4)
        row = index.row()
        is_placeholder = bool(index.data(StockItemsListModel.PlaceholderRole))
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        active_flag = bool(index.data(StockItemsListModel.ActiveRole))
        active_visible = active_flag and self._active_visual_enabled
        bulk_selected = bool(index.data(StockItemsListModel.BulkSelectedRole))

        if is_placeholder:
            painter.setPen(QColor(STOCK_CARD_PLACEHOLDER_TEXT_COLOR))
            painter.setFont(QFont(STOCK_CARD_FONT_FAMILY, STOCK_CARD_PLACEHOLDER_FONT_SIZE))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, index.data(StockItemsListModel.TitleRole) or "")
            painter.restore()
            return

        self._paint_card_surface(
            painter,
            rect,
            hovered=hovered,
            card_selected=bulk_selected,
            active_visible=active_visible,
        )

        title = index.data(StockItemsListModel.TitleRole) or ""
        subtitle = index.data(StockItemsListModel.SubtitleRole) or ""
        extra = index.data(StockItemsListModel.ExtraRole) or ""
        icon_path = index.data(StockItemsListModel.IconRole) or ""
        has_source = True

        x = rect.left() + 10
        icon_rect = QRect(x, rect.center().y() - self._icon_size // 2, self._icon_size, self._icon_size)
        dpr = painter.device().devicePixelRatioF()
        pix = self._load_icon(icon_path, dpr)
        if pix is not None:
            pr = pix.devicePixelRatio() or 1.0
            pw = int(pix.width() / pr)
            ph = int(pix.height() / pr)
            target = QRect(0, 0, pw, ph)
            target.moveCenter(icon_rect.center())
            painter.drawPixmap(target, pix)
        else:
            painter.setBrush(QColor(STOCK_CARD_ICON_PLACEHOLDER_COLOR))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(icon_rect, 8, 8)

        x = icon_rect.right() + 12
        select_rect, source_rect = self._button_rects(rect, has_source=has_source, view=option.widget)
        inline_layout = _stock_card_inline_geometry(
            row_rect=rect,
            text_left=x,
            anchor_left=(source_rect.left() if source_rect is not None else select_rect.left()),
        )
        text_right = int(inline_layout.get("text_right") or 0)
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

        if source_rect is not None:
            hover_source = self._hover_source_row == row
            pressed_source = self._pressed_source_row == row
            source_draw = source_rect
            if pressed_source:
                source_draw = source_rect.adjusted(1, 1, -1, -1)
                painter.setBrush(QColor(STOCK_CARD_SELECTED_BUTTON_FILL_COLOR))
                painter.setPen(QPen(QColor(STOCK_CARD_SELECTED_BUTTON_BORDER_COLOR), 1))
            elif hover_source:
                painter.setBrush(QColor(STOCK_CARD_HOVER_BUTTON_FILL_COLOR))
                painter.setPen(QPen(QColor(STOCK_CARD_HOVER_BUTTON_BORDER_COLOR), 1))
            else:
                painter.setBrush(QColor(STOCK_CARD_IDLE_BUTTON_FILL_COLOR))
                painter.setPen(QPen(QColor(STOCK_CARD_IDLE_BUTTON_BORDER_COLOR), 1))
            painter.drawRoundedRect(source_draw, 8, 8)
            painter.setPen(QColor(STOCK_CARD_ACTION_TEXT_COLOR))
            painter.setFont(QFont(STOCK_CARD_FONT_FAMILY, STOCK_CARD_ACTION_FONT_SIZE, QFont.Weight.Bold))
            painter.drawText(source_rect, Qt.AlignmentFlag.AlignCenter, STOCK_ITEM_SOURCE_BUTTON_TEXT)

        self._paint_hook_button(
            painter,
            select_rect,
            index=index,
            row=row,
            hook_selected=bulk_selected,
        )

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if bool(index.data(StockItemsListModel.PlaceholderRole)):
            return False
        rect = option.rect.adjusted(6, 4, -6, -4)
        view = option.widget
        has_source = True
        icon_rect = QRect(
            rect.left() + 10,
            rect.center().y() - self._icon_size // 2,
            self._icon_size,
            self._icon_size,
        )
        select_rect, source_rect = self._button_rects(rect, has_source=has_source, view=view)

        def _clear_hover_state() -> bool:
            changed = False
            if self._hover_row == index.row():
                self._hover_row = None
                changed = True
            if self._hover_source_row == index.row():
                self._hover_source_row = None
                changed = True
            return changed

        def _clear_pressed_state() -> bool:
            changed = False
            if self._pressed_row == index.row():
                self._pressed_row = None
                changed = True
            if self._pressed_source_row == index.row():
                self._pressed_source_row = None
                changed = True
            return changed

        if event.type() == QEvent.Type.MouseMove:
            pos = event.position().toPoint()
            hovering_select = select_rect.contains(pos)
            hovering_source = bool(source_rect is not None and source_rect.contains(pos))
            changed = False
            if hovering_select:
                if self._hover_row != index.row():
                    self._hover_row = index.row()
                    changed = True
                if self._hover_source_row == index.row():
                    self._hover_source_row = None
                    changed = True
            elif hovering_source:
                if self._hover_source_row != index.row():
                    self._hover_source_row = index.row()
                    changed = True
                if self._hover_row == index.row():
                    self._hover_row = None
                    changed = True
            else:
                changed = _clear_hover_state()
            if changed and view:
                view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
        if event.type() == QEvent.Type.Leave:
            changed = False
            if self._hover_row is not None:
                self._hover_row = None
                changed = True
            if self._hover_source_row is not None:
                self._hover_source_row = None
                changed = True
            if changed and view:
                view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if icon_rect.contains(pos):
                if view is not None and hasattr(view, "set_active_row"):
                    try:
                        view.set_active_row(index.row())
                    except Exception:
                        pass
                return True
            if source_rect is not None and source_rect.contains(pos):
                self._pressed_source_row = index.row()
                if view:
                    view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
                return True
            if select_rect.contains(pos):
                self._pressed_row = index.row()
                if view:
                    view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
                return True
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if icon_rect.contains(pos):
                rec = index.data(StockItemsListModel.ItemRole)
                if view is not None and hasattr(view, "set_active_row"):
                    try:
                        view.set_active_row(index.row())
                    except Exception:
                        pass
                if callable(self._on_image_click):
                    try:
                        self._on_image_click(index, rec)
                    except Exception:
                        pass
                return True
            select_was_pressed = self._pressed_row == index.row()
            source_was_pressed = self._pressed_source_row == index.row()
            _clear_pressed_state()
            if view:
                view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
            if source_was_pressed and source_rect is not None and source_rect.contains(pos):
                if view is not None and hasattr(view, "_mark_hook_click_handled"):
                    view._mark_hook_click_handled()
                if callable(self._on_source_button):
                    try:
                        self._on_source_button(index)
                    except Exception:
                        pass
                return True
            if select_was_pressed and select_rect.contains(pos):
                self._mark_view_action_click_handled(view)
                is_selected = bool(index.data(StockItemsListModel.BulkSelectedRole))
                next_selected = not is_selected
                return bool(self._handle_hook_activated(model, index, next_selected))
        return super().editorEvent(event, model, option, index)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        _ = option
        _ = index
        return QSize(0, self._row_height)


class InlineReadonlyMetric(QWidget):
    def __init__(self, parent=None, *, label: str = "Aktif Maliyet"):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.label = QLabel(label)
        self.label.setStyleSheet("font-size: 10px; color: #64748B; font-weight: 700;")
        self.label.setFixedHeight(16)
        layout.addWidget(self.label)

        self.input = QLineEdit(self)
        self.input.setObjectName("Input")
        self.input.setReadOnly(True)
        self.input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input.setFrame(False)
        self.input.setFixedHeight(30)
        self.input.setStyleSheet(
            "QLineEdit#Input {"
            "background: #F8FAFC;"
            "border: 1px solid #E2E8F0;"
            "border-radius: 12px;"
            "padding: 0 8px;"
            "color: #0F172A;"
            "font-weight: 700;"
            "}"
        )
        layout.addWidget(self.input)
        self.setMinimumHeight(60)

    def set_text(self, text: str) -> None:
        self.input.setText(str(text or "-"))

    def set_compact(self, compact: bool, *, label_height: int = 10, input_height: int = 14) -> None:
        if compact:
            self.label.setFixedHeight(max(8, int(label_height)))
            self.label.setStyleSheet("font-size: 8px; color: #64748B; font-weight: 700;")
            self.input.setFixedHeight(max(12, int(input_height)))
            self.input.setStyleSheet(
                "QLineEdit#Input {"
                "background: #F8FAFC;"
                "border: 1px solid #E2E8F0;"
                "border-radius: 7px;"
                "padding: 0 6px;"
                "color: #0F172A;"
                "font-size: 10px;"
                "font-weight: 700;"
                "}"
            )
            self.setMinimumHeight(max(24, int(label_height) + int(input_height) + 4))
        else:
            self.label.setFixedHeight(16)
            self.label.setStyleSheet("font-size: 10px; color: #64748B; font-weight: 700;")
            self.input.setFixedHeight(30)
            self.input.setStyleSheet(
                "QLineEdit#Input {"
                "background: #F8FAFC;"
                "border: 1px solid #E2E8F0;"
                "border-radius: 12px;"
                "padding: 0 8px;"
                "color: #0F172A;"
                "font-weight: 700;"
                "}"
            )
            self.setMinimumHeight(60)


class InlineCostMetricPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        self.desi_label = QLabel("Desi", self)
        self.desi_label.setStyleSheet("font-size: 10px; color: #64748B; font-weight: 800;")
        self.desi_label.setFixedHeight(13)
        layout.addWidget(self.desi_label)

        self.desi_input = QLineEdit(self)
        self.desi_input.setObjectName("Input")
        self.desi_input.setReadOnly(True)
        self.desi_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.desi_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.desi_input.setFrame(False)
        self.desi_input.setFixedHeight(18)
        self.desi_input.setStyleSheet(
            "QLineEdit#Input {"
            "background: #F8FAFC;"
            "border: 1px solid #E2E8F0;"
            "border-radius: 9px;"
            "padding: 0 8px;"
            "color: #0F172A;"
            "font-size: 11px;"
            "font-weight: 800;"
            "}"
        )
        layout.addWidget(self.desi_input)

        self.label = QLabel("Aktif Maliyet", self)
        self.label.setStyleSheet("font-size: 11px; color: #64748B; font-weight: 800;")
        self.label.setFixedHeight(16)
        layout.addWidget(self.label)

        self.input = QLineEdit(self)
        self.input.setObjectName("Input")
        self.input.setReadOnly(True)
        self.input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input.setFrame(False)
        self.input.setFixedHeight(22)
        self.input.setStyleSheet(
            "QLineEdit#Input {"
            "background: #F8FAFC;"
            "border: 1px solid #E2E8F0;"
            "border-radius: 11px;"
            "padding: 0 10px;"
            "color: #0F172A;"
            "font-size: 12px;"
            "font-weight: 800;"
            "}"
        )
        layout.addWidget(self.input)
        self.setMinimumHeight(56)

    def set_text(self, text: str) -> None:
        self.input.setText(str(text or "-"))

    def set_desi_text(self, text: str) -> None:
        self.desi_input.setText(str(text or "-"))


class InlineStockAdjustControls(QWidget):
    submitted = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.avg_price = InlineCostMetricPanel(self)
        self.stock = LabeledActionInput(
            self,
            label="Stok",
            placeholder="0",
            button_text="OK",
            idle_glow=False,
        )
        self.stock.setMinimumHeight(56)
        self.stock.input.setObjectName("Input")
        self.stock.input.setFixedHeight(30)
        if hasattr(self.stock, "_sync_sizes"):
            self.stock._sync_sizes()

        validator = QDoubleValidator(0.0, 1_000_000_000.0, 3, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.stock.setValidator(validator)

        self._idle_reset_timer = QTimer(self)
        self._idle_reset_timer.setSingleShot(True)
        self._idle_reset_timer.timeout.connect(self._on_idle_reset_timeout)

        self.stock.submitted.connect(lambda _v: self.submitted.emit(self.stock_value()))

    def place_controls(self, stock_rect: QRect, avg_rect: QRect, desi_rect: QRect | None = None) -> None:
        _ = desi_rect
        bounds = self.rect()
        if bounds.isValid() and bounds.width() > 0 and bounds.height() > 0:
            if avg_rect.top() < 0:
                avg_rect.moveTop(0)
            if stock_rect.top() < 0:
                stock_rect.moveTop(0)
            if avg_rect.bottom() > bounds.bottom():
                avg_rect.setBottom(bounds.bottom())
            if stock_rect.bottom() > bounds.bottom():
                stock_rect.setBottom(bounds.bottom())
        self.stock.setGeometry(stock_rect)
        self.avg_price.setGeometry(avg_rect)

    def set_value(self, value: Any) -> None:
        self.stock.setValue(_fmt_num(value, default="0"))

    def set_average_value(self, value: Any, *, currency: str | None = None) -> None:
        if value is None:
            self.avg_price.set_text("-")
            return
        try:
            num = float(value)
        except Exception:
            self.avg_price.set_text("-")
            return
        price_text = _fmt_num(num, default="-")
        cur = str(currency or "").strip().upper()
        if cur:
            price_text = f"{price_text} {cur}"
        self.avg_price.set_text(price_text)

    def set_desi_value(self, value: Any) -> None:
        if value is None:
            self.avg_price.set_desi_text("-")
            return
        try:
            num = float(value)
        except Exception:
            self.avg_price.set_desi_text("-")
            return
        if num <= 0:
            self.avg_price.set_desi_text("-")
            return
        self.avg_price.set_desi_text(_fmt_num(num, default="-"))

    def stock_value(self) -> Optional[float]:
        text = (self.stock.value() or "").strip().replace(",", ".")
        if not text:
            return None
        try:
            value = float(text)
        except Exception:
            return None
        if value < 0:
            return None
        return value

    def set_state(self, state: str) -> None:
        self.stock.setState(state)

    def schedule_idle_reset(self, delay_ms: int) -> None:
        ms = max(0, int(delay_ms or 0))
        self._idle_reset_timer.start(ms)

    def _on_idle_reset_timeout(self) -> None:
        try:
            self.stock.setState("idle")
        except RuntimeError:
            # Widget already disposed by list refresh.
            return

    def set_in_view(self, active: bool) -> None:
        inp = getattr(self.stock, "input", None)
        if inp is not None and hasattr(inp, "setInView"):
            try:
                inp.setInView(active)
            except Exception:
                pass


class StockItemsListWidget(QListView):
    selection_changed = pyqtSignal()
    page_changed = pyqtSignal(int, int, int, int)
    item_selected = pyqtSignal(object)
    item_clicked = pyqtSignal(object)
    record_clicked = pyqtSignal(object)
    selection_button_clicked = pyqtSignal(object, bool)
    source_button_clicked = pyqtSignal(object)
    bulk_selection_changed = pyqtSignal(int)
    selection_state_changed = pyqtSignal()
    background_clicked = pyqtSignal()
    blank_area_clicked = pyqtSignal()

    def __init__(self, parent=None, *, adjust_stock_cb=None, open_image_cb=None):
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
        self._adjust_stock_cb = adjust_stock_cb
        self._open_image_cb = open_image_cb
        self._inline_stock_controls: dict[int, InlineStockAdjustControls] = {}
        self._all_items: list[dict[str, Any]] = []
        self._active_item_id: Optional[int] = None
        self._bulk_selected_ids: set[int] = set()
        self.page_size: int = 20
        self.current_page: int = 1

        self._model = StockItemsListModel(parent=self, on_selection_changed=self._emit_state_changed)
        self._delegate = StockItemsListDelegate(
            self,
            on_select_button=self._on_select_button_clicked,
            on_image_click=self._on_image_clicked,
            on_source_button=self._on_source_button_clicked,
        )
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
        if bool(index.data(StockItemsListModel.PlaceholderRole)):
            return False
        rec = index.data(StockItemsListModel.ItemRole)
        if not isinstance(rec, dict):
            return False
        if not self._external_selection_handler_enabled:
            item_id = self._item_id(rec)
            if item_id is not None:
                if selected:
                    self._bulk_selected_ids.add(item_id)
                else:
                    self._bulk_selected_ids.discard(item_id)
            self._model.set_bulk_selected_row(index.row(), bool(selected))
        self.selection_button_clicked.emit(rec, bool(selected))
        return True

    def _on_source_button_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        if bool(index.data(StockItemsListModel.PlaceholderRole)):
            return
        rec = index.data(StockItemsListModel.ItemRole)
        if isinstance(rec, dict):
            self.source_button_clicked.emit(rec)

    def _on_image_clicked(self, index: QModelIndex, rec: Any) -> None:
        if not index.isValid():
            return
        if isinstance(rec, dict):
            self._active_item_id = self._item_id(rec)
        self._model.set_selected(index.row(), True)
        self._emit_state_changed()
        if isinstance(rec, dict) and callable(self._open_image_cb):
            try:
                self._open_image_cb(rec)
            except Exception:
                pass

    def set_active_row(self, row: int) -> None:
        rec = self._model.item_at(int(row)) or {}
        item = rec.get("item") if isinstance(rec, dict) else None
        self._active_item_id = self._item_id(item)
        self._model.set_selected(int(row), True)
        self._emit_state_changed()

    def _on_clicked(self, index: QModelIndex) -> None:
        if self._hook_click_handled:
            self._hook_click_handled = False
            return
        if not index.isValid():
            return
        if bool(index.data(StockItemsListModel.PlaceholderRole)):
            self.background_clicked.emit()
            self.blank_area_clicked.emit()
            return
        rec = index.data(StockItemsListModel.ItemRole)
        if isinstance(rec, dict):
            self._active_item_id = self._item_id(rec)
            self.item_clicked.emit(rec)
            self.record_clicked.emit(rec)
        self._model.set_selected(index.row(), True)

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
        return tuple(sorted(str(item_id) for item_id in self._bulk_selected_ids))

    def _emit_selection_state_if_needed(self, *, force: bool = False) -> None:
        signature = self._selection_signature()
        if not force and signature == self._last_selection_signature:
            return
        self._last_selection_signature = signature
        self.selection_state_changed.emit()

    def _emit_state_changed(self) -> None:
        active_row = self._model.active_row()
        self._set_active_border_animation_enabled(active_row >= 0 and self._active_spin_allowed)
        self.item_selected.emit(self.selected_item())
        self._emit_selection_state_if_needed()
        self.selection_changed.emit()
        self.bulk_selection_changed.emit(self.bulk_selected_count())
        self.page_changed.emit(self.current_page, self.get_total_pages(), self.total_record_count(), self.shown_count())

    def _rebuild_inline_stock_controls(self) -> None:
        for ctrl in self._inline_stock_controls.values():
            ctrl.setParent(None)
            ctrl.deleteLater()
        self._inline_stock_controls = {}

        for row in range(self._model.rowCount()):
            rec = self._model.item_at(row) or {}
            if rec.get("placeholder"):
                continue
            item = rec.get("item")
            if not isinstance(item, dict):
                continue
            ctrl = InlineStockAdjustControls(self.viewport())
            ctrl.set_value(item.get("on_hand", 0))
            ctrl.set_desi_value(_stock_item_unit_desi(item))
            ctrl.set_average_value(
                item.get("avg_unit_cost"),
                currency=item.get("avg_cost_currency") or item.get("default_currency") or "TRY",
            )
            ctrl.submitted.connect(lambda _v, r=row: self._apply_inline_stock_for_row(r))
            self._inline_stock_controls[row] = ctrl

        self._position_inline_stock_controls()

    def _apply_inline_stock_for_row(self, row: int) -> None:
        ctrl = self._inline_stock_controls.get(row)
        if ctrl is None:
            return
        rec = self._model.item_at(row) or {}
        if rec.get("placeholder"):
            return
        item = rec.get("item")
        if not isinstance(item, dict):
            return

        target_qty = ctrl.stock_value()
        if target_qty is None:
            ctrl.set_state("error")
            ctrl.schedule_idle_reset(1600)
            return

        self._active_item_id = self._item_id(item)
        self._model.set_selected(row, True)
        self._emit_state_changed()
        ctrl.set_state("pending")

        def _feedback(result: Any) -> None:
            status = "pending"
            if result is True:
                status = "success"
            elif result is False:
                status = "error"
            elif isinstance(result, str):
                candidate = result.strip().lower()
                if candidate in {"idle", "pending", "success", "error"}:
                    status = candidate
            ctrl.set_state(status)
            if status in {"success", "error"}:
                ctrl.schedule_idle_reset(1800)
            elif status == "idle":
                ctrl.set_state("idle")

        if not callable(self._adjust_stock_cb):
            _feedback("error")
            return

        try:
            self._adjust_stock_cb(item, float(target_qty), _feedback)
        except TypeError:
            outcome = self._adjust_stock_cb(item, float(target_qty))
            _feedback(outcome)
        except Exception as e:
            try:
                self.error("Hata", f"Stok düzeltme akışı sırasında hata oluştu:\n{e}")
            except Exception:
                pass
            _feedback("error")

    def _position_inline_stock_controls(self) -> None:
        for row in range(self._model.rowCount()):
            ctrl = self._inline_stock_controls.get(row)
            if ctrl is None:
                continue
            rec = self._model.item_at(row) or {}
            if rec.get("placeholder"):
                ctrl.setVisible(False)
                ctrl.set_in_view(False)
                continue
            idx = self._model.index(row)
            rect = self.visualRect(idx)
            if rect.isNull() or rect.height() <= 0:
                ctrl.setVisible(False)
                ctrl.set_in_view(False)
                continue

            row_rect = rect.adjusted(6, 4, -6, -4)
            select_rect, source_rect = self._delegate._button_rects(
                row_rect,
                has_source=True,
                view=self,
            )
            anchor_rect = source_rect if source_rect is not None else select_rect
            icon_right = row_rect.left() + 10 + self._delegate._icon_size
            text_left = icon_right + 12
            inline_layout = _stock_card_inline_geometry(
                row_rect=row_rect,
                text_left=text_left,
                anchor_left=anchor_rect.left(),
            )
            if not bool(inline_layout.get("visible")):
                ctrl.setVisible(False)
                ctrl.set_in_view(False)
                continue

            stock_rect = inline_layout["stock_rect"]
            avg_rect = inline_layout["avg_rect"]
            controls_rect = avg_rect.united(stock_rect).adjusted(-2, -2, 2, 2)
            ctrl.setGeometry(controls_rect)
            ctrl.place_controls(
                stock_rect.translated(-controls_rect.left(), -controls_rect.top()),
                avg_rect.translated(-controls_rect.left(), -controls_rect.top()),
            )
            ctrl.setVisible(True)
            ctrl.set_in_view(True)
            ctrl.raise_()

    def set_items(
        self,
        items: list[dict],
        *,
        keep_selected_id: Optional[int] = None,
        keep_bulk_selected_ids: Optional[list[int]] = None,
    ) -> None:
        selected_id = keep_selected_id if keep_selected_id is not None else self.selected_item_id()
        bulk_ids = keep_bulk_selected_ids if keep_bulk_selected_ids is not None else list(self._bulk_selected_ids)
        self._all_items = items if isinstance(items, list) else list(items or [])
        available_ids = {
            item_id for item_id in (self._item_id(item) for item in self._all_items)
            if item_id is not None
        }
        self._bulk_selected_ids = {
            item_id for item_id in (self._coerce_item_id(value) for value in (bulk_ids or []))
            if item_id is not None and item_id in available_ids
        }
        normalized_selected_id = self._coerce_item_id(selected_id)
        self._active_item_id = normalized_selected_id if normalized_selected_id in available_ids else None
        self.current_page = 1
        self._build_page()

    @staticmethod
    def _coerce_item_id(value: Any) -> Optional[int]:
        try:
            parsed = int(value)
        except Exception:
            return None
        return parsed if parsed > 0 else None

    @classmethod
    def _item_id(cls, item: Any) -> Optional[int]:
        return cls._coerce_item_id(_stock_item_record_id(item))

    def _page_bounds(self) -> tuple[int, int]:
        page_size = max(1, int(self.page_size or 20))
        total = len(self._all_items or [])
        total_pages = max(1, (total + page_size - 1) // page_size)
        self.current_page = max(1, min(int(self.current_page or 1), total_pages))
        start = (self.current_page - 1) * page_size
        return start, min(start + page_size, total)

    def _current_page_items(self) -> list[dict]:
        start, end = self._page_bounds()
        return (self._all_items or [])[start:end]

    def _build_page(self) -> None:
        self._model.set_items(
            self._current_page_items(),
            selected_id=self._active_item_id,
            bulk_selected_ids=list(self._bulk_selected_ids),
        )
        self._rebuild_inline_stock_controls()
        self.scrollToTop()
        self._emit_state_changed()

    def set_selected_id(self, item_id: Optional[int]) -> bool:
        self._active_item_id = self._coerce_item_id(item_id)
        ok = self._model.set_selected_by_id(self._active_item_id)
        self._emit_state_changed()
        return ok

    def set_external_selection_handler_enabled(self, enabled: bool) -> None:
        self._external_selection_handler_enabled = bool(enabled)

    def set_record_selected(self, record: Optional[dict], selected: bool) -> None:
        item_id = self._item_id(record)
        if item_id is None:
            return
        if selected:
            self._bulk_selected_ids.add(item_id)
        else:
            self._bulk_selected_ids.discard(item_id)
        for row in range(self._model.rowCount()):
            row_item = self._model.item_at(row) or {}
            item = row_item.get("item")
            current_id = self._item_id(item)
            if current_id != item_id:
                continue
            self._model.set_bulk_selected_row(row, bool(selected))
            return
        self._emit_state_changed()

    def clear_selection(self) -> None:
        self.clear_active_selection()

    def clear_active_selection(self) -> None:
        self._active_item_id = None
        self._model.clear_active_row()
        self._emit_state_changed()

    def clear_bulk_selection(self) -> None:
        if self._bulk_selected_ids:
            self._bulk_selected_ids.clear()
        self._model.clear_bulk_selected_rows()
        self._emit_state_changed()

    def get_selected_records(self) -> list[dict]:
        return self.bulk_selected_items()

    def selected_item(self) -> dict | None:
        active_id = self._active_item_id
        if active_id is None:
            return None
        for item in self._all_items or []:
            if self._item_id(item) == active_id:
                return item
        return None

    def selected_item_id(self) -> Optional[int]:
        return self._active_item_id

    def bulk_selected_items(self) -> list[dict]:
        selected_ids = set(self._bulk_selected_ids)
        return [
            item for item in (self._all_items or [])
            if (self._item_id(item) in selected_ids)
        ]

    def bulk_selected_ids(self) -> list[int]:
        selected_ids = set(self._bulk_selected_ids)
        return [
            item_id for item_id in (self._item_id(item) for item in (self._all_items or []))
            if item_id is not None and item_id in selected_ids
        ]

    def bulk_selected_count(self) -> int:
        return len(self._bulk_selected_ids)

    def total_record_count(self) -> int:
        return len(self._all_items)

    def shown_count(self) -> int:
        return self._model.rowCount()

    def get_total_pages(self) -> int:
        total = len(self._all_items or [])
        if total <= 0:
            return 1
        page_size = max(1, int(self.page_size or 20))
        return (total + page_size - 1) // page_size

    def set_page_size(self, size: int) -> None:
        self.page_size = max(1, int(size or 20))
        self.current_page = 1
        self._build_page()

    def go_to_page(self, page: int) -> None:
        self.current_page = max(1, min(int(page or 1), self.get_total_pages()))
        self._build_page()

    def next_page(self) -> None:
        self.go_to_page(self.current_page + 1)

    def prev_page(self) -> None:
        self.go_to_page(self.current_page - 1)

    def clear_selected_records(self) -> None:
        self.clear_bulk_selection()

    def select_all_filtered_records(self) -> None:
        all_ids = {
            item_id for item_id in (self._item_id(item) for item in (self._all_items or []))
            if item_id is not None
        }
        if all_ids - self._bulk_selected_ids:
            self._bulk_selected_ids.update(all_ids)
            self._build_page()
        else:
            self._emit_state_changed()

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
        self.viewport().update()

    def _tick_active_border_animation(self) -> None:
        if self._active_border_animation_enabled:
            self._delegate.advance_spin_phase(1.35)
        if self._guide_select_animation_enabled:
            self._delegate.advance_guide_phase(1.35)
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_dynamic_row_width()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._position_inline_stock_controls()

    def sync_dynamic_row_width(self) -> None:
        try:
            self.doItemsLayout()
            self._position_inline_stock_controls()
            self.viewport().update()
        except Exception:
            return


class ImagePreviewDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(STOCK_IMAGE_PREVIEW_TITLE)
        self.setMinimumSize(680, 520)
        self._pixmap: Optional[QPixmap] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        self.label = QLabel(STOCK_IMAGE_PREVIEW_LOAD_ERROR_TEXT)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("background:#0f172a;color:#e2e8f0;border-radius:8px;")
        root.addWidget(self.label, 1)

    def set_image_path(self, path: str | None) -> None:
        pix = QPixmap(path or "")
        if pix.isNull():
            self._pixmap = None
            self.label.setText(STOCK_IMAGE_PREVIEW_EMPTY_TEXT)
            return
        self._pixmap = pix
        self._update_pixmap()

    def _update_pixmap(self) -> None:
        if not self._pixmap:
            return
        scaled = self._pixmap.scaled(
            self.label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()


class StockItemsWorkspaceBehaviorAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, dialog: "StockItemManagerDialog") -> None:
        self.dialog = dialog

    @property
    def list_widget(self):
        return self.dialog.items_list

    def get_mode(self) -> str:
        return str(self.dialog._left_mode or "edit")

    def set_mode(self, mode: str) -> None:
        self.dialog._set_left_mode(mode)

    def get_active_key(self) -> str:
        return str(self.dialog.items_list.selected_item_id() or "")

    def get_selected_count(self) -> int:
        return int(self.dialog.items_list.bulk_selected_count() or 0)

    def get_record_key(self, record) -> str:
        return str(_stock_item_record_id(record) or "")

    def prepare_new(self) -> None:
        self.dialog._prepare_new_item_workspace()

    def activate_record(self, record) -> None:
        self.dialog.items_list.set_selected_id(_stock_item_record_id(record))

    def clear_active(self) -> None:
        self.dialog.items_list.clear_active_selection()
        self.dialog._clear_item_workspace_state()

    def apply_selection(self, record, selected: bool) -> None:
        self.dialog.items_list.set_record_selected(record, bool(selected))

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self.dialog.items_list.set_select_button_guide_enabled(bool(enabled))

    def on_state_changed(self) -> None:
        self.dialog._sync_item_workspace_state()

    def edit_guidance_message(self) -> str:
        return "Düzenlemek için sağdaki listeden bir stok kartı seç."

    def bulk_guidance_message(self) -> str:
        return "Toplu işlem için sağdaki listeden en az bir kartı SEÇ ile işaretle."

class StockItemManagerDialog(FullscreenDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Stok Kartları")
        self._left_mode = "edit"
        self._image_preview: ImagePreviewDialog | None = None
        self._refresh_worker: SyncWorker | None = None
        self._refresh_seq = 0
        self._has_loaded_once = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)
        outer.addLayout(content_row, 1)

        self._left_stick_size = 620
        self._workspace = RecordWorkspaceScaffold(
            self,
            left_title=STOCK_MANAGER_LEFT_EDIT_TITLE,
            left_subtitle="Düzenlemek için sağdaki listeden bir stok kartı seç.",
            filters_title=STOCK_MANAGER_FILTERS_TITLE,
            records_title="Kart Listesi",
            style_sheet=None,
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
            shell_kwargs={**STOCK_MANAGER_WORKSPACE_SHELL_KWARGS, "left_stick_size": self._left_stick_size, "left_collapse_trigger": 560, "min_right_width": 720},
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": "Yeni stok kartı paneli",
                    "icon_path": str(ASSETS_DIR / "yeni-kayit.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": "Stok kartı düzenleme paneli",
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
        self._item_splitter = splitter
        self._left_card = self._workspace.left_card
        self.left_panel_title = self._workspace.left_card.title_label
        self.left_panel_hint = self._workspace.left_card.subtitle_label
        self._editor_scroll = self._workspace.editor_scroll
        self._editor_actions_wrap = self._workspace.editor_actions_host
        self.bulk_panel = self._workspace.bulk_panel
        form_host = QWidget(self._workspace.editor_host)
        form_host.setObjectName("FormBody")
        form = QFormLayout(form_host)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.le_id = QLineEdit()
        self.le_id.setEnabled(False)
        self.le_id.setPlaceholderText("Seçince dolar")

        self.le_sku = QLineEdit(); self.le_sku.setPlaceholderText("Örn: SKU-245")
        self.le_name = QLineEdit(); self.le_name.setPlaceholderText("Ürün adı")
        self.le_barcode = QLineEdit(); self.le_barcode.setPlaceholderText("Barkod (ops.)")
        self.btn_generate_barcode = _inline_action_btn("Üret",  min_h=38, min_w=88)
        self.btn_generate_barcode.clicked.connect(self._generate_barcode)

        self.cb_item_type = SwitchSelectWidget(multi=False)
        for label, value in ITEM_TYPE_OPTIONS:
            self.cb_item_type.addItem(label, value)
        self.cb_item_type.setCurrentIndex(0)

        self.cb_unit = SwitchSelectWidget(multi=False)
        self.cb_unit.addItems(UNIT_OPTIONS)
        self.cb_unit.setCurrentText("adet")
        self.cb_brand = SwitchSelectWidget(multi=False)
        self.cb_brand.setPlaceholderText("Marka ara/seç")
        self.btn_brand_manage = _inline_action_btn("Marka Yönet", min_h=38, min_w=128)
        self.btn_brand_manage.clicked.connect(self._open_brand_manager)

        brand_row = QHBoxLayout()
        brand_row.addWidget(self.cb_brand, 1)
        brand_row.addWidget(self.btn_brand_manage)
        self.cb_category = SwitchSelectWidget(multi=False, include_all=False, empty_text="Seçiniz")
        self.cb_category.setPlaceholderText("Kategori ara/seç")
        self.cb_category.setCurrentIndex(-1)
        self.cb_category.currentIndexChanged.connect(self._on_category_changed)
        self.btn_upper_group_manage = _inline_action_btn("Üst Grup Yönet", min_h=38, min_w=138)
        self.btn_upper_group_manage.clicked.connect(self._open_upper_group_manager)
        category_row = QHBoxLayout()
        category_row.addWidget(self.cb_category, 1)
        category_row.addWidget(self.btn_upper_group_manage)
        self.cb_sub_category = SwitchSelectWidget(multi=False, include_all=False, empty_text="Seçiniz")
        self.cb_sub_category.setPlaceholderText("Önce üst grup seçin")
        self.btn_sub_group_manage = _inline_action_btn("Alt Grup Yönet", min_h=38, min_w=128)
        self.btn_sub_group_manage.clicked.connect(self._open_sub_group_manager)
        sub_group_row = QHBoxLayout()
        sub_group_row.addWidget(self.cb_sub_category, 1)
        sub_group_row.addWidget(self.btn_sub_group_manage)
        self.le_model_code = QLineEdit(); self.le_model_code.setPlaceholderText("Model/Kod (ops.)")
        self.le_manufacturer = QLineEdit(); self.le_manufacturer.setPlaceholderText("Üretici (ops.)")
        self.le_gtip_code = QLineEdit(); self.le_gtip_code.setPlaceholderText("GTİP kodu (ops.)")
        self.le_custom_label = QLineEdit(); self.le_custom_label.setPlaceholderText("Özel kod/etiket (ops.)")
        self.le_location_code = QLineEdit(); self.le_location_code.setPlaceholderText("Depo/lokasyon kodu (ops.)")

        self.sp_min_stock = NumberStepper(minimum=0, maximum=10_000_000, step=1)
        self.sp_max_stock = NumberStepper(minimum=0, maximum=10_000_000, step=1)
        self.sp_safety_stock = NumberStepper(minimum=0, maximum=10_000_000, step=1)
        self.sp_reorder_point = NumberStepper(minimum=0, maximum=10_000_000, step=1)
        self.sp_reorder_qty = NumberStepper(minimum=0, maximum=10_000_000, step=1)
        self.sp_lead_time_days = NumberStepper(minimum=0, maximum=3650, step=1)
        self.sp_shelf_life_days = NumberStepper(minimum=0, maximum=36500, step=1)
        self.le_vat_rate = CircularPercentageInput(decimals=2, diameter=118); self.le_vat_rate.setPlaceholderText("KDV")
        vat_row_host = QWidget()
        vat_row_layout = QHBoxLayout(vat_row_host)
        vat_row_layout.setContentsMargins(0, 0, 0, 0)
        vat_row_layout.setSpacing(0)
        vat_row_layout.addWidget(self.le_vat_rate, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        vat_row_layout.addStretch(1)
        vat_label = QLabel("KDV (%)")
        vat_label.setMinimumHeight(118)
        vat_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.chk_active = SwitchButton()
        self.chk_active.setChecked(True)
        self.chk_serial_tracking = SwitchButton()
        self.chk_lot_tracking = SwitchButton()
        self.chk_allow_negative_stock = SwitchButton()

        self.item_file_picker = FileBadgePicker(
            button_text="Dosya Seç",
            clear_text=STOCK_MANAGER_CLEAR_TEXT,
            dialog_title="Belge / Fotoğraf Seç",
            dialog_filter="Tüm Dosyalar (*.*)",
            allow_multiple=True,
            show_clear_button=True,
            open_on_click=True,
        )

        self.le_weight = NumericPulseLineEdit(decimals=3)
        self.le_weight.setPlaceholderText("Ağırlık (kg)")
        self.le_len = NumericPulseLineEdit(decimals=2)
        self.le_len.setPlaceholderText("Boy (cm)")
        self.le_wid = NumericPulseLineEdit(decimals=2)
        self.le_wid.setPlaceholderText("En (cm)")
        self.le_hei = NumericPulseLineEdit(decimals=2)
        self.le_hei.setPlaceholderText("Yükseklik (cm)")

        dim_row = QHBoxLayout()
        dim_row.setSpacing(10)
        dim_row.addWidget(self.le_len, 1)
        dim_row.addWidget(self.le_wid, 1)
        dim_row.addWidget(self.le_hei, 1)

        self.te_description = QTextEdit(); self.te_description.setPlaceholderText("Açıklama (ops.)")
        self.te_note = QTextEdit(); self.te_note.setPlaceholderText("Not (ops.)")

        track_row = QHBoxLayout()
        track_row.setSpacing(10)
        track_row.addWidget(QLabel("Seri"))
        track_row.addWidget(self.chk_serial_tracking)
        track_row.addWidget(QLabel("Lot"))
        track_row.addWidget(self.chk_lot_tracking)
        track_row.addStretch()

        form.addRow("SKU *", self.le_sku)
        form.addRow("Ad *", self.le_name)
        barcode_wrap = QWidget()
        barcode_layout = QHBoxLayout(barcode_wrap)
        barcode_layout.setContentsMargins(0, 0, 0, 0)
        barcode_layout.setSpacing(8)
        barcode_layout.addWidget(self.le_barcode, 1)
        barcode_layout.addWidget(self.btn_generate_barcode)
        form.addRow("Barkod", barcode_wrap)
        form.addRow("Tip", self.cb_item_type)
        form.addRow("Birim", self.cb_unit)
        form.addRow("Marka", brand_row)
        form.addRow("Üst Grup", category_row)
        form.addRow("Alt Grup", sub_group_row)
        form.addRow("Model/Kod", self.le_model_code)
        form.addRow("Üretici", self.le_manufacturer)
        form.addRow("GTİP Kodu", self.le_gtip_code)
        form.addRow("Özel Kod", self.le_custom_label)
        form.addRow("Lokasyon", self.le_location_code)
        form.addRow("Min Stok", self.sp_min_stock)
        form.addRow("Maks Stok", self.sp_max_stock)
        form.addRow("Emniyet Stoku", self.sp_safety_stock)
        form.addRow("Yeniden Sip. Noktası", self.sp_reorder_point)
        form.addRow("Standart Sip. Miktarı", self.sp_reorder_qty)
        form.addRow("Tedarik Süresi (gün)", self.sp_lead_time_days)
        form.addRow("Raf Ömrü (gün)", self.sp_shelf_life_days)
        form.addRow(vat_label, vat_row_host)
        form.addRow("Takip", track_row)
        form.addRow("Ağırlık", self.le_weight)
        form.addRow("Ebat (cm)", dim_row)
        neg_row = QHBoxLayout()
        neg_row.setSpacing(10)
        neg_row.addWidget(QLabel("İzin"))
        neg_row.addWidget(self.chk_allow_negative_stock)
        neg_row.addStretch()
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_row.addWidget(QLabel("Aktif"))
        status_row.addWidget(self.chk_active)
        status_row.addStretch()
        form.addRow("Belge/Fotoğraf", self.item_file_picker)
        form.addRow("Açıklama", self.te_description)
        form.addRow("Not", self.te_note)
        form.addRow("Negatif Stok", neg_row)
        form.addRow("Durum", status_row)

        self.cb_unit.setToolTip("ürünün stok birimi (adet, kg, paket vb.).")
        self.sp_min_stock.setToolTip("Kritik eşik. Stok bu değerin altına inince uyar verir.")

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text=STOCK_MANAGER_CLEAR_TEXT,
            save_new_text="Stok Kartı Kaydet",
            save_edit_text=STOCK_MANAGER_SAVE_EDIT_TEXT,
            delete_text=STOCK_MANAGER_DELETE_TEXT,
        )
        self.btn_new = self._workspace.editor_action_bar.clear_button
        self.btn_save = self._workspace.editor_action_bar.save_button
        self.btn_delete = self._workspace.editor_action_bar.delete_button

        self._workspace.editor_action_bar.clearRequested.connect(self.clear_form)
        self._workspace.editor_action_bar.saveRequested.connect(self.save_or_update)
        self._workspace.editor_action_bar.deleteRequested.connect(self.delete_item)

        bulk_content = QWidget(self.bulk_panel)
        bulk_layout = QVBoxLayout(bulk_content)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.setSpacing(8)
        bulk_layout.setContentsMargins(10, 8, 10, 8)
        bulk_layout.addWidget(QLabel(STOCK_MANAGER_BULK_TITLE, objectName="Section"))
        self.bulk_summary = QLabel("Seçili kart: 0", objectName="SubTitle")
        self.bulk_summary.setWordWrap(True)
        bulk_hint = QLabel("SEÇ ile işaretlediğin stok kartları üzerinde toplu işlem yapabilirsin.", objectName="SubTitle")
        bulk_hint.setWordWrap(True)
        self.btn_bulk_mark_active = _btn("Seçilenleri Aktif Yap", "Primary", 42)
        self.btn_bulk_mark_passive = _btn("Seçilenleri Pasif Yap", "Secondary", 42)
        self.btn_bulk_clear = _btn(STOCK_MANAGER_BULK_CLEAR_TEXT, "Ghost", 42)
        self.btn_bulk_mark_active.clicked.connect(lambda: self._bulk_set_active_state(True))
        self.btn_bulk_mark_passive.clicked.connect(lambda: self._bulk_set_active_state(False))
        self.btn_bulk_clear.clicked.connect(self._clear_bulk_selection)
        bulk_layout.addWidget(self.bulk_summary)
        bulk_layout.addWidget(bulk_hint)
        bulk_layout.addWidget(self.btn_bulk_mark_active)
        bulk_layout.addWidget(self.btn_bulk_mark_passive)
        bulk_layout.addWidget(self.btn_bulk_clear)
        bulk_layout.addStretch(1)
        self.bulk_panel.hide()

        self.le_search = QLineEdit()
        self.le_search.setObjectName("Search")
        self.le_search.setPlaceholderText("Ara: sku / ad / barkod / model / gtip / marka / kategori")
        self.le_search.textChanged.connect(self._schedule_filter)

        self.cb_status = SwitchSelectWidget(title="Durum", all_text="Tümü", multi=False, include_all=True)
        self.cb_status.addItems(["Aktif", "Pasif"])
        self.cb_status.currentIndexChanged.connect(self._schedule_filter)

        self.cb_filter_type = SwitchSelectWidget(title="Tip", all_text="Tümü", multi=False, include_all=True)
        for label, value in ITEM_TYPE_OPTIONS:
            self.cb_filter_type.addItem(label, value)
        self.cb_filter_type.currentIndexChanged.connect(self._schedule_filter)

        self.cb_filter_unit = SwitchSelectWidget(title="Birim", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_unit.currentIndexChanged.connect(self._schedule_filter)

        self.cb_filter_brand = SwitchSelectWidget(title="Marka", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_brand.currentIndexChanged.connect(self._schedule_filter)

        self.cb_filter_category = SwitchSelectWidget(title="Üst Grup", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_category.currentIndexChanged.connect(self._schedule_filter)

        self.cb_filter_sub_category = SwitchSelectWidget(title="Alt Grup", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_sub_category.currentIndexChanged.connect(self._schedule_filter)

        self.cb_filter_has_image = SwitchSelectWidget(title="Görsel", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_has_image.addItem("Var", "has")
        self.cb_filter_has_image.addItem("Yok", "none")
        self.cb_filter_has_image.currentIndexChanged.connect(self._schedule_filter)

        self.cb_filter_tracking = SwitchSelectWidget(title="Takip", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_tracking.addItem("Seri", "serial")
        self.cb_filter_tracking.addItem("Lot", "lot")
        self.cb_filter_tracking.addItem("Seri + Lot", "both")
        self.cb_filter_tracking.addItem("Yok", "none")
        self.cb_filter_tracking.currentIndexChanged.connect(self._schedule_filter)

        self.btn_reset_filters = _btn(STOCK_MANAGER_RESET_FILTERS_TEXT, "SoftDanger", 40)
        self.btn_reset_filters.clicked.connect(self._reset_list_filters)

        filter_row_top = QHBoxLayout()
        filter_row_top.setSpacing(8)
        filter_row_top.addWidget(self.le_search, 3)
        filter_row_top.addWidget(self.cb_status, 1)
        filter_row_top.addWidget(self.cb_filter_type, 1)
        filter_row_top.addWidget(self.btn_reset_filters, 0)

        filter_row_mid = QHBoxLayout()
        filter_row_mid.setSpacing(8)
        filter_row_mid.addWidget(self.cb_filter_brand, 1)
        filter_row_mid.addWidget(self.cb_filter_category, 1)
        filter_row_mid.addWidget(self.cb_filter_sub_category, 1)

        filter_row_bottom = QHBoxLayout()
        filter_row_bottom.setSpacing(8)
        filter_row_bottom.addWidget(self.cb_filter_unit, 1)
        filter_row_bottom.addWidget(self.cb_filter_has_image, 1)
        filter_row_bottom.addWidget(self.cb_filter_tracking, 1)

        filters_host = QWidget(self._workspace.filters_host)
        filters_layout = QVBoxLayout(filters_host)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(8)
        filters_layout.addLayout(filter_row_top)
        filters_layout.addLayout(filter_row_mid)
        filters_layout.addLayout(filter_row_bottom)
        filters_layout.addStretch(1)

        self.items_list = StockItemsListWidget(
            adjust_stock_cb=self._on_inline_stock_adjustment,
            open_image_cb=self._open_item_image_preview,
        )
        self.items_list.item_selected.connect(self.on_row_selected)
        self.items_list.source_button_clicked.connect(self._on_item_source_button_clicked)
        self.items_list.bulk_selection_changed.connect(self._on_bulk_selection_changed)
        self._workspace.set_editor_widget(form_host)
        self._workspace.set_bulk_widget(bulk_content)
        self._workspace.set_filters_widget(filters_host)
        self._workspace.set_list_widget(self.items_list)
        self._workspace.footer_bar.setObjectName("BottomBar")
        self._workspace.footer_bar.page_size_label.setText("Sayfa başına")

        splitter.setSizes([0, 1540])
        splitter.setHandleWidth(6)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)

        self._cache: list[dict] = []
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(120)
        self._filter_timer.timeout.connect(self.apply_filter)
        self._forced_item_id: Optional[int] = None
        self._workspace_adapter = StockItemsWorkspaceBehaviorAdapter(self)
        self._workspace_behavior = self._workspace.create_behavior_controller(
            adapter=self._workspace_adapter,
        )
        self._refresh_category_choices()
        self._on_category_changed()
        _apply_stock_composite_theme(self)
        self._set_left_mode("edit")
        self._update_bulk_panel_state()
        self._sync_guidance_overlays_geometry()
        self._sync_focus_guidance_state()
        self._sync_sidebar_state_from_splitter()
        self._sync_delete_enabled()

    # ---------- helpers ----------
    def showEvent(self, event):
        super().showEvent(event)
        if self._has_loaded_once:
            return
        self._has_loaded_once = True
        self._set_items_list_loading(True)
        QTimer.singleShot(0, self.refresh_table)

    def _prepare_new_item_workspace(self):
        self.items_list.clear_active_selection()
        self.clear_form(clear_list_selection=False, fast=True)
        self._set_left_mode("new")

    def _clear_item_workspace_state(self):
        self.clear_form(clear_list_selection=False, fast=True)
        self._sync_delete_enabled()

    def _sync_item_workspace_state(self):
        self._update_bulk_panel_state()
        self._sync_guidance_overlays_geometry()
        self._sync_card_spin_state()
        self._sync_delete_enabled()

    def _sync_delete_enabled(self):
        has_id = bool((self.le_id.text() or "").strip())
        self.btn_delete.setEnabled(has_id and self._left_mode in {"edit", "new"})

    def _schedule_filter(self, *_args):
        self._filter_timer.start()

    def _set_items_list_loading(self, busy: bool, message: str = "Kartlar yükleniyor...") -> None:
        self._workspace.set_list_loading(bool(busy), message=message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_items_list_layout()
        self._sync_guidance_overlays_geometry()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()
        self._sync_card_spin_state()

    def _refresh_items_list_layout(self):
        self.items_list.sync_dynamic_row_width()

    def _is_editor_panel_open(self) -> bool:
        return self._workspace_shell.is_left_panel_open()

    def _refresh_left_panel_header(self):
        mode = str(self._left_mode or "edit").lower()
        if mode == "new":
            self.left_panel_title.setText(STOCK_MANAGER_LEFT_NEW_TITLE)
            self.left_panel_hint.setText("Yeni stok kartı bilgilerini doldurup kaydet.")
            return
        if mode == "bulk":
            self.left_panel_title.setText(STOCK_MANAGER_LEFT_BULK_TITLE)
            self.left_panel_hint.setText("SEÇ ile işaretlenen stok kartları için toplu işlem yapabilirsin.")
            return
        self.left_panel_title.setText(STOCK_MANAGER_LEFT_EDIT_TITLE)
        selected = self.items_list.selected_item()
        if selected is None:
            self.left_panel_hint.setText("Düzenlemek için sağdaki listeden bir stok kartı seç.")
            return
        self.left_panel_hint.setText(f"Seçili kart: {str(selected.get('name') or '-').strip()}")

    def _set_left_mode(self, mode: str):
        mode_key = str(mode or "").lower()
        if mode_key not in {"new", "edit", "bulk"}:
            mode_key = "edit"
        self._left_mode = mode_key
        self._workspace.set_editor_action_mode(mode_key)
        show_editor = self._left_mode in {"new", "edit"}
        self._editor_scroll.setVisible(show_editor)
        self.bulk_panel.setVisible(not show_editor)
        self._refresh_left_panel_header()
        self._sync_sidebar_state_from_splitter()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()
        self._sync_card_spin_state()

    def _update_bulk_panel_state(self):
        count = self.items_list.bulk_selected_count()
        self.bulk_summary.setText(f"Seçili kart: {count}")
        enabled = count > 0
        self.btn_bulk_mark_active.setEnabled(enabled)
        self.btn_bulk_mark_passive.setEnabled(enabled)

    def _on_bulk_selection_changed(self, _count: int):
        self._update_bulk_panel_state()
        if self._left_mode == "bulk" and self._is_editor_panel_open() and self.items_list.bulk_selected_count() <= 0:
            self._close_editor_panel()
            return
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def _clear_bulk_selection(self):
        self.items_list.clear_bulk_selection()
        self._update_bulk_panel_state()
        if self._left_mode == "bulk" and self._is_editor_panel_open():
            self._close_editor_panel()
        else:
            self._sync_sidebar_state_from_splitter()

    def _bulk_set_active_state(self, active_state: bool):
        selected_items = self.items_list.bulk_selected_items()
        if not selected_items:
            self.error("Hata", "Toplu işlem için en az bir kart seçmelisin.")
            return
        selected_ids = self.items_list.bulk_selected_ids()
        success_count = 0
        failed_count = 0
        failed_messages: list[str] = []
        for rec in selected_items:
            try:
                pk = int(_stock_item_record_id(rec) or 0)
            except Exception:
                failed_count += 1
                continue
            res = action_update_item(pk=pk, update_data={"is_active": bool(active_state)})
            if res.success:
                success_count += 1
            else:
                failed_count += 1
                failed_messages.append(f"{pk}: {res.message}")

        self.refresh_table(keep_bulk_selected_ids=selected_ids)
        if failed_count <= 0:
            self.info("OK", f"{success_count} kart güncellendi.")
            return
        detail = "\n".join(failed_messages[:5])
        self.error(
            "Kısmi Bağarı",
            f"{success_count} kart güncellendi, {failed_count} kart güncellenemedi."
            + (f"\n{detail}" if detail else ""),
        )

    def _sync_guidance_overlays_geometry(self):
        self._workspace.sync_list_loading_geometry()
        self._workspace_shell.sync_guidance_geometry()

    def _sync_focus_guidance_state(self):
        self._workspace_behavior.sync_state()

    def _update_edit_lock_state(self):
        return

    def _sync_card_spin_state(self):
        panel_open = self._is_editor_panel_open()
        selected = self.items_list.selected_item()
        allow_spin = self._left_mode == "edit" and panel_open and selected is not None
        self.items_list.set_active_spin_allowed(bool(allow_spin))

    def _sync_sidebar_state_from_splitter(self):
        self._workspace.sync_list_loading_geometry()
        self._workspace_shell.sync_guidance_geometry()
        self._workspace_behavior.sync_state()
        self._refresh_items_list_layout()

    def _open_editor_panel(self):
        self._workspace_shell.open_left_panel(min_left=320, min_right=260)
        self._sync_sidebar_state_from_splitter()

    def _clear_active_edit_selection(self):
        self.items_list.clear_active_selection()
        self.clear_form(clear_list_selection=False, fast=True)
        self._sync_delete_enabled()

    def _close_editor_panel(self):
        if self._left_mode == "edit":
            self._clear_active_edit_selection()
        self._workspace_shell.close_left_panel()
        self._sync_sidebar_state_from_splitter()

    def _open_new_form(self):
        self._workspace_behavior.handle_panel_sidebar_toggled("new", True)

    def _open_item_image_preview(self, rec: Optional[dict]) -> None:
        if not isinstance(rec, dict):
            return
        raw = rec.get("image_path")
        path = _first_image_path(raw)
        if self._image_preview is None:
            self._image_preview = ImagePreviewDialog(self)
        preview = self._image_preview
        preview.set_image_path(path or None)
        preview.show()
        preview.raise_()
        preview.activateWindow()

    def _on_item_source_button_clicked(self, rec: Optional[dict]) -> None:
        if not isinstance(rec, dict):
            return
        try:
            item_id = int(rec.get("id") or 0)
        except Exception:
            item_id = 0
        if item_id <= 0:
            self.error("Hata", "Geçersiz stok kartı.")
            return

        item_name = str(rec.get("name") or f"#{item_id}").strip()
        from .stock_tx_dialog import StockTxDialog
        source_dialog = StockTxDialog(self)
        source_dialog.setWindowTitle(f"Stok Giriş / Çıkış • Stok Kaynağı • {item_name}")
        source_dialog._set_filter_range_widgets(
            QDateTime.currentDateTime().addYears(-20),
            QDateTime.currentDateTime().addYears(1),
        )
        source_dialog.apply_forced_item_filter(
            item_id=item_id,
        )
        source_dialog.open_full()

    def clear_form(self, *, clear_list_selection: bool = True, fast: bool = False):
        try:
            self.setUpdatesEnabled(False)
            self.le_id.clear()
            self.le_sku.clear()
            self.le_name.clear()
            self.le_barcode.clear()
            self.cb_item_type.setCurrentIndex(0)
            self.cb_unit.setCurrentText("adet")
            self.cb_brand.setCurrentIndex(-1)

            with QSignalBlocker(self.cb_category):
                self.cb_category.setCurrentIndex(-1)

            with QSignalBlocker(self.cb_sub_category):
                self.cb_sub_category.clear()
                self.cb_sub_category.setPlaceholderText("Önce üst grup seçin")

            self.le_model_code.clear()
            self.le_manufacturer.clear()
            self.le_gtip_code.clear()
            self.le_custom_label.clear()
            self.le_location_code.clear()
            self.sp_min_stock.setValue(0)
            self.sp_max_stock.setValue(0)
            self.sp_safety_stock.setValue(0)
            self.sp_reorder_point.setValue(0)
            self.sp_reorder_qty.setValue(0)
            self.sp_lead_time_days.setValue(0)
            self.sp_shelf_life_days.setValue(0)
            self.le_vat_rate.setText("")
            self.le_weight.setText("")
            self.le_len.setText("")
            self.le_wid.setText("")
            self.le_hei.setText("")
            self.chk_active.setChecked(True)
            self.chk_serial_tracking.setChecked(False)
            self.chk_lot_tracking.setChecked(False)
            self.chk_allow_negative_stock.setChecked(False)
            self.item_file_picker.clearFiles()
            self.te_description.clear()
            self.te_note.clear()

            if clear_list_selection:
                self.items_list.clear_selection()
            self._sync_delete_enabled()
        finally:
            self.setUpdatesEnabled(True)
            if not fast:
                self.update()

    def _generate_barcode(self):
        res = action_generate_unique_barcode(prefix="869")
        if res.success:
            barcode = (res.data or {}).get("barcode")
            if barcode:
                self.le_barcode.setText(str(barcode))
        else:
            self.error("Hata", res.message or "Barkod üretilemedi.")

    # ---------- data ----------
    def refresh_table(
        self,
        *,
        keep_selected_id: Optional[int] = None,
        keep_bulk_selected_ids: Optional[list[int]] = None,
    ):
        if keep_selected_id is None:
            keep_selected_id = self.items_list.selected_item_id()
        if keep_bulk_selected_ids is None:
            keep_bulk_selected_ids = self.items_list.bulk_selected_ids()
        keep_bulk_ids = list(keep_bulk_selected_ids or [])
        self._refresh_seq += 1
        seq = int(self._refresh_seq)
        self._set_items_list_loading(True, "Kartlar yükleniyor...")

        worker = SyncWorker(_load_stock_items_snapshot, parent=self)
        self._refresh_worker = worker

        def _after(result):
            if seq != self._refresh_seq:
                return
            try:
                self.items_list.set_items([], keep_selected_id=None, keep_bulk_selected_ids=keep_bulk_ids)
                self._cache.clear()

                if not getattr(result, "success", False):
                    self.error("Hata", getattr(result, "message", "Kayıtlar yüklenemedi."))
                    return

                payload = (getattr(result, "data", None) or {}).get("result", {}) or {}
                res = payload.get("items_result")
                bal_res = payload.get("balances_result")

                on_hand_by_item_id: dict[int, float] = {}
                avg_cost_by_item_id: dict[int, float] = {}
                avg_cost_currency_by_item_id: dict[int, str] = {}

                if getattr(bal_res, "success", False):
                    bal_data = getattr(bal_res, "data", None) or {}
                    for row in (bal_data.get("records", []) or []):
                        if not isinstance(row, dict):
                            continue
                        item_obj = row.get("item")
                        item_id = getattr(item_obj, "pk", None)
                        if item_id in (None, ""):
                            item_id = getattr(item_obj, "id", None)
                        try:
                            item_key = int(item_id)
                        except Exception:
                            continue
                        on_hand_by_item_id[item_key] = float(row.get("on_hand", 0) or 0)
                        avg_raw = row.get("avg_unit_cost")
                        if avg_raw is not None:
                            try:
                                avg_cost_by_item_id[item_key] = float(avg_raw)
                            except Exception:
                                pass
                        cur = str(row.get("avg_cost_currency") or "").strip().upper()
                        if cur:
                            avg_cost_currency_by_item_id[item_key] = cur

                if not getattr(res, "success", False):
                    self.error("Hata", getattr(res, "message", "Kayıtlar yüklenemedi."))
                    return

                records = ((getattr(res, "data", None) or {}).get("records", []) or [])
                for it in records:
                    item_id = getattr(it, "pk", None)
                    if item_id in (None, ""):
                        item_id = getattr(it, "id", None)
                    try:
                        item_key = int(item_id)
                    except Exception:
                        item_key = -1
                    sku = getattr(it, "sku", "") or ""
                    name = getattr(it, "name", "") or ""
                    barcode = getattr(it, "barcode", None)
                    item_type = getattr(it, "item_type", None)
                    unit = getattr(it, "unit", "") or ""
                    brand = getattr(it, "brand", None)
                    category = getattr(it, "category", None)
                    sub_category = getattr(it, "sub_category", None)
                    model_code = getattr(it, "model_code", None)
                    manufacturer = getattr(it, "manufacturer", None)
                    gtip_code = getattr(it, "gtip_code", None)
                    custom_label = getattr(it, "custom_label", None)
                    location_code = getattr(it, "location_code", None)
                    image_path = getattr(it, "image_path", None)
                    description = getattr(it, "description", None)
                    note = getattr(it, "note", None)
                    serial_tracking = bool(getattr(it, "serial_tracking", False))
                    lot_tracking = bool(getattr(it, "lot_tracking", False))

                    search_parts = [
                        sku,
                        name,
                        barcode,
                        brand,
                        category,
                        sub_category,
                        model_code,
                        manufacturer,
                        gtip_code,
                    ]
                    search_blob = " ".join(str(v) for v in search_parts if v not in (None, "")).casefold()

                    self._cache.append({
                        "id": item_id,
                        "_id_norm": item_key if item_key > 0 else None,
                        "sku": sku,
                        "name": name,
                        "barcode": barcode,
                        "item_type": item_type,
                        "unit": unit,
                        "brand": brand,
                        "category": category,
                        "sub_category": sub_category,
                        "model_code": model_code,
                        "manufacturer": manufacturer,
                        "gtip_code": gtip_code,
                        "custom_label": custom_label,
                        "location_code": location_code,
                        "image_path": image_path,
                        "description": description,
                        "note": note,
                        "is_active": bool(getattr(it, "is_active", True)),
                        "min_stock": getattr(it, "min_stock", None),
                        "max_stock": getattr(it, "max_stock", None),
                        "safety_stock": getattr(it, "safety_stock", None),
                        "reorder_point": getattr(it, "reorder_point", None),
                        "reorder_qty": getattr(it, "reorder_qty", None),
                        "lead_time_days": getattr(it, "lead_time_days", None),
                        "shelf_life_days": getattr(it, "shelf_life_days", None),
                        "serial_tracking": serial_tracking,
                        "lot_tracking": lot_tracking,
                        "allow_negative_stock": bool(getattr(it, "allow_negative_stock", False)),
                        "vat_rate": getattr(it, "vat_rate", None),
                        "weight_kg": getattr(it, "weight_kg", None),
                        "length_cm": getattr(it, "length_cm", None),
                        "width_cm": getattr(it, "width_cm", None),
                        "height_cm": getattr(it, "height_cm", None),
                        "on_hand": float(on_hand_by_item_id.get(item_key, 0) or 0),
                        "avg_unit_cost": avg_cost_by_item_id.get(item_key),
                        "avg_cost_currency": (
                            avg_cost_currency_by_item_id.get(item_key)
                            or (getattr(it, "default_currency", "TRY") or "TRY")
                        ),
                        "default_cost": getattr(it, "default_cost", None),
                        "default_currency": getattr(it, "default_currency", "TRY") or "TRY",
                        "_unit_norm": str(unit).strip().casefold(),
                        "_brand_norm": str(brand or "").strip().casefold(),
                        "_category_norm": str(category or "").strip().casefold(),
                        "_sub_category_norm": str(sub_category or "").strip().casefold(),
                        "_has_image": bool(_first_image_path(image_path)),
                        "_search_blob": search_blob,
                    })

                self._refresh_list_filters()
                self.apply_filter(keep_selected_id=keep_selected_id, keep_bulk_selected_ids=keep_bulk_ids)
                self._refresh_brand_choices()
            finally:
                self._set_items_list_loading(False)

        def _on_finished():
            if seq == self._refresh_seq:
                self._set_items_list_loading(False)

        worker.result_ready.connect(_after)
        worker.finished.connect(_on_finished)
        worker.start()

    def _refresh_brand_choices(self):
        current = self.cb_brand.currentText()
        res = action_list_brands()
        with QSignalBlocker(self.cb_brand):
            self.cb_brand.clear()
            if res.success:
                for b in (res.data.get("records", []) or []):
                    self.cb_brand.addItem(getattr(b, "name", "") or "")
        if current:
            self._set_brand_selection(current)

    def _refresh_category_choices(self):
        current = (self.cb_category.currentText() or "").strip()
        with QSignalBlocker(self.cb_category):
            self.cb_category.clear()
            res = action_list_upper_groups()
            if res.success:
                for name in (res.data.get("records", []) or []):
                    txt = str(name or "").strip()
                    if txt:
                        self.cb_category.addItem(txt)
        if current:
            idx = self.cb_category.findText(current)
            if idx >= 0:
                self.cb_category.setCurrentIndex(idx)
            else:
                self.cb_category.setCurrentIndex(-1)

    def _set_brand_selection(self, brand_name: Optional[str]):
        name = (brand_name or "").strip()
        if not name:
            self.cb_brand.setCurrentIndex(-1)
            return
        idx = self.cb_brand.findText(name)
        if idx >= 0:
            self.cb_brand.setCurrentIndex(idx)
        else:
            self.cb_brand.addItem(name)
            self.cb_brand.setCurrentText(name)

    def _set_category_selection(self, category_name: Optional[str]):
        name = (category_name or "").strip()
        if not name:
            self.cb_category.setCurrentIndex(-1)
            self._on_category_changed()
            return
        idx = self.cb_category.findText(name)
        if idx >= 0:
            self.cb_category.setCurrentIndex(idx)
        else:
            self.cb_category.addItem(name)
            self.cb_category.setCurrentText(name)
        self._on_category_changed()

    def _on_category_changed(self):
        category_name = (self.cb_category.currentText() or "").strip()
        current_sub = (self.cb_sub_category.currentText() or "").strip()
        suggestions: list[str] = []
        if category_name:
            res = action_list_sub_groups(category=category_name, only_active=True)
            if res.success:
                suggestions = [
                    str(getattr(rec, "name", "") or "").strip()
                    for rec in (res.data.get("records", []) or [])
                    if str(getattr(rec, "name", "") or "").strip()
                ]
        self.cb_sub_category.clear()
        if suggestions:
            self.cb_sub_category.addItems(suggestions)
        if current_sub:
            idx = self.cb_sub_category.findText(current_sub)
            if idx >= 0:
                self.cb_sub_category.setCurrentIndex(idx)
        if not category_name:
            self.cb_sub_category.setPlaceholderText("Önce üst grup seçin")
        elif suggestions:
            self.cb_sub_category.setPlaceholderText("Alt grup seçin")
        else:
            self.cb_sub_category.setPlaceholderText("Alt grup yok, 'Alt Grup Yönet' ile ekleyin")

    def _open_brand_manager(self):
        from .brand_manager_dialog import BrandManagerDialog
        BrandManagerDialog(self).open_full()
        self._refresh_brand_choices()

    def _open_upper_group_manager(self):
        from .upper_group_manager_dialog import UpperGroupManagerDialog
        dlg = UpperGroupManagerDialog(self)
        dlg.open_full()
        self._refresh_category_choices()
        self._on_category_changed()

    def _open_sub_group_manager(self):
        from .sub_group_manager_dialog import SubGroupManagerDialog
        dlg = SubGroupManagerDialog(self)
        current_category = (self.cb_category.currentText() or "").strip()
        dlg.set_category(current_category)
        dlg.open_full()
        self._refresh_category_choices()
        self._on_category_changed()

    def _set_filter_options(self, widget: SwitchSelectWidget, values: list[str]):
        current_data = widget.currentData()
        with QSignalBlocker(widget):
            widget.clear()
            seen: set[str] = set()
            for value in values:
                text = str(value or "").strip()
                if not text:
                    continue
                key = text.casefold()
                if key in seen:
                    continue
                seen.add(key)
                widget.addItem(text, text)
            restored = False
            if current_data not in (None, "all"):
                try:
                    idx = widget.findData(current_data)
                except Exception:
                    idx = -1
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                    restored = True
            if not restored:
                widget.setCurrentIndex(0)

    def _refresh_list_filters(self):
        units = sorted({str(r.get("unit") or "").strip() for r in self._cache if str(r.get("unit") or "").strip()})
        brands = sorted({str(r.get("brand") or "").strip() for r in self._cache if str(r.get("brand") or "").strip()})
        categories = sorted({str(r.get("category") or "").strip() for r in self._cache if str(r.get("category") or "").strip()})
        sub_categories = sorted({str(r.get("sub_category") or "").strip() for r in self._cache if str(r.get("sub_category") or "").strip()})

        self._set_filter_options(self.cb_filter_unit, units)
        self._set_filter_options(self.cb_filter_brand, brands)
        self._set_filter_options(self.cb_filter_category, categories)
        self._set_filter_options(self.cb_filter_sub_category, sub_categories)

    @staticmethod
    def _normalize_item_id(value: Any) -> Optional[int]:
        try:
            item_id = int(value)
        except Exception:
            return None
        return item_id if item_id > 0 else None

    def clear_forced_item_filter(self) -> None:
        self._forced_item_id = None

    def apply_forced_item_filter(self, *, item_id: int) -> None:
        normalized_item_id = self._normalize_item_id(item_id)
        if normalized_item_id is None:
            self.clear_forced_item_filter()
            return
        self._forced_item_id = normalized_item_id
        self.le_search.clear()
        self.cb_status.setCurrentText("Tümü")
        self.cb_filter_type.setCurrentIndex(0)
        self.cb_filter_unit.setCurrentIndex(0)
        self.cb_filter_brand.setCurrentIndex(0)
        self.cb_filter_category.setCurrentIndex(0)
        self.cb_filter_sub_category.setCurrentIndex(0)
        self.cb_filter_has_image.setCurrentIndex(0)
        self.cb_filter_tracking.setCurrentIndex(0)
        self.apply_filter(keep_selected_id=normalized_item_id, keep_bulk_selected_ids=[])
        # Stok hareketinden açılan kart ekranında sol panel sabit/kapalı kalsın.
        self._close_editor_panel()

    def _reset_list_filters(self):
        self.clear_forced_item_filter()
        self.le_search.clear()
        self.cb_status.setCurrentText("Tümü")
        self.cb_filter_type.setCurrentIndex(0)
        self.cb_filter_unit.setCurrentIndex(0)
        self.cb_filter_brand.setCurrentIndex(0)
        self.cb_filter_category.setCurrentIndex(0)
        self.cb_filter_sub_category.setCurrentIndex(0)
        self.cb_filter_has_image.setCurrentIndex(0)
        self.cb_filter_tracking.setCurrentIndex(0)
        self.apply_filter()

    def apply_filter(
        self,
        *,
        keep_selected_id: Optional[int] = None,
        keep_bulk_selected_ids: Optional[list[int]] = None,
    ):
        if self._filter_timer.isActive():
            self._filter_timer.stop()

        q = (self.le_search.text() or "").strip().casefold()
        rows = self._cache

        forced_item_id = self._normalize_item_id(self._forced_item_id)
        if forced_item_id is not None:
            rows = [r for r in rows if r.get("_id_norm") == forced_item_id]

        status = self.cb_status.currentText()
        if status == "Aktif":
            rows = [r for r in rows if r["is_active"]]
        elif status == "Pasif":
            rows = [r for r in rows if not r["is_active"]]

        type_filter = self.cb_filter_type.currentData()
        if type_filter not in (None, "all"):
            rows = [r for r in rows if str(r.get("item_type") or "") == str(type_filter)]

        unit_filter = self.cb_filter_unit.currentData()
        if unit_filter not in (None, "all"):
            unit_norm = str(unit_filter).strip().casefold()
            rows = [r for r in rows if r.get("_unit_norm", "") == unit_norm]

        brand_filter = self.cb_filter_brand.currentData()
        if brand_filter not in (None, "all"):
            brand_norm = str(brand_filter).strip().casefold()
            rows = [r for r in rows if r.get("_brand_norm", "") == brand_norm]

        category_filter = self.cb_filter_category.currentData()
        if category_filter not in (None, "all"):
            category_norm = str(category_filter).strip().casefold()
            rows = [r for r in rows if r.get("_category_norm", "") == category_norm]

        sub_category_filter = self.cb_filter_sub_category.currentData()
        if sub_category_filter not in (None, "all"):
            sub_category_norm = str(sub_category_filter).strip().casefold()
            rows = [r for r in rows if r.get("_sub_category_norm", "") == sub_category_norm]

        image_filter = self.cb_filter_has_image.currentData()
        if image_filter == "has":
            rows = [r for r in rows if bool(r.get("_has_image"))]
        elif image_filter == "none":
            rows = [r for r in rows if not bool(r.get("_has_image"))]

        tracking_filter = self.cb_filter_tracking.currentData()
        if tracking_filter == "serial":
            rows = [r for r in rows if bool(r.get("serial_tracking"))]
        elif tracking_filter == "lot":
            rows = [r for r in rows if bool(r.get("lot_tracking"))]
        elif tracking_filter == "both":
            rows = [r for r in rows if bool(r.get("serial_tracking")) and bool(r.get("lot_tracking"))]
        elif tracking_filter == "none":
            rows = [r for r in rows if not bool(r.get("serial_tracking")) and not bool(r.get("lot_tracking"))]

        if q:
            rows = [r for r in rows if q in str(r.get("_search_blob") or "")]

        active_id = keep_selected_id
        if active_id is None:
            active_id = self.items_list.selected_item_id()
        if active_id is None and forced_item_id is not None:
            active_id = forced_item_id
        if active_id is None:
            try:
                active_id = int((self.le_id.text() or "").strip())
            except Exception:
                active_id = None
        bulk_ids = keep_bulk_selected_ids
        if bulk_ids is None:
            bulk_ids = self.items_list.bulk_selected_ids()
        self.items_list.set_items(rows, keep_selected_id=active_id, keep_bulk_selected_ids=bulk_ids)

        if len(rows) == 0:
            self.clear_form(clear_list_selection=False)
            # Forced filtre modunda boş sonuç paneli açmasın; sadece liste tarafı kalsın.
            if self._left_mode in {"edit", "bulk"} or forced_item_id is not None:
                self._close_editor_panel()
        else:
            self._sync_delete_enabled()
        self._update_bulk_panel_state()
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()
        self._sync_card_spin_state()

    def on_row_selected(self, rec: Optional[dict] = None):
        if rec is None:
            rec = self.items_list.selected_item()
        if not rec:
            self.clear_form(clear_list_selection=False, fast=True)
            self._sync_delete_enabled()
            self._refresh_left_panel_header()
            self._sync_focus_guidance_state()
            self._update_edit_lock_state()
            self._sync_card_spin_state()
            if self._left_mode == "edit" and self._is_editor_panel_open():
                self._sync_sidebar_state_from_splitter()
            return

        if self._left_mode != "edit":
            self._sync_delete_enabled()
            self._refresh_left_panel_header()
            return

        self.le_id.setText(str(rec["id"]))
        self.le_sku.setText(rec["sku"])
        self.le_name.setText(rec["name"])
        self.le_barcode.setText("" if rec["barcode"] is None else str(rec["barcode"]))

        itype = str(rec["item_type"] or StockItemType.physical.value)
        idx = self.cb_item_type.findData(itype)
        if idx < 0:
            idx = 0
        self.cb_item_type.setCurrentIndex(idx)

        self.cb_unit.setCurrentText(rec["unit"] or "adet")
        self._set_brand_selection(rec["brand"])
        self._set_category_selection(rec["category"])
        self.cb_sub_category.setCurrentText("" if rec.get("sub_category") is None else str(rec.get("sub_category")))
        self.le_model_code.setText("" if rec.get("model_code") is None else str(rec.get("model_code")))
        self.le_manufacturer.setText("" if rec.get("manufacturer") is None else str(rec.get("manufacturer")))
        self.le_gtip_code.setText("" if rec.get("gtip_code") is None else str(rec.get("gtip_code")))
        self.le_custom_label.setText("" if rec.get("custom_label") is None else str(rec.get("custom_label")))
        self.le_location_code.setText("" if rec.get("location_code") is None else str(rec.get("location_code")))

        self.sp_min_stock.setValue(int(rec["min_stock"] or 0))
        self.sp_max_stock.setValue(int(rec.get("max_stock") or 0))
        self.sp_safety_stock.setValue(int(rec.get("safety_stock") or 0))
        self.sp_reorder_point.setValue(int(rec.get("reorder_point") or 0))
        self.sp_reorder_qty.setValue(int(rec.get("reorder_qty") or 0))
        self.sp_lead_time_days.setValue(int(rec.get("lead_time_days") or 0))
        self.sp_shelf_life_days.setValue(int(rec.get("shelf_life_days") or 0))
        if rec.get("vat_rate") is not None:
            self.le_vat_rate.setValue(float(rec.get("vat_rate")))
        else:
            self.le_vat_rate.setText("")
        if rec.get("weight_kg") is not None:
            self.le_weight.setValue(float(rec.get("weight_kg")))
        else:
            self.le_weight.setText("")
        if rec.get("length_cm") is not None:
            self.le_len.setValue(float(rec.get("length_cm")))
        else:
            self.le_len.setText("")
        if rec.get("width_cm") is not None:
            self.le_wid.setValue(float(rec.get("width_cm")))
        else:
            self.le_wid.setText("")
        if rec.get("height_cm") is not None:
            self.le_hei.setValue(float(rec.get("height_cm")))
        else:
            self.le_hei.setText("")
        self.chk_active.setChecked(bool(rec["is_active"]))
        self.chk_serial_tracking.setChecked(bool(rec.get("serial_tracking")))
        self.chk_lot_tracking.setChecked(bool(rec.get("lot_tracking")))
        self.chk_allow_negative_stock.setChecked(bool(rec.get("allow_negative_stock")))

        item_files: list[str] = []
        if rec.get("image_path"):
            try:
                item_files = json.loads(rec.get("image_path")) or []
            except Exception:
                item_files = [str(rec.get("image_path"))]
        self.item_file_picker.setFiles(item_files, emit_signal=False)

        self.te_description.setPlainText("" if rec["description"] is None else str(rec["description"]))
        self.te_note.setPlainText("" if rec["note"] is None else str(rec["note"]))

        self._sync_delete_enabled()
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()
        self._sync_card_spin_state()

    def _on_inline_stock_adjustment(self, item: dict, target_qty: float, feedback_cb=None):
        def _feedback(state: str):
            if callable(feedback_cb):
                try:
                    feedback_cb(state)
                except Exception:
                    pass

        if not isinstance(item, dict):
            _feedback("error")
            return

        try:
            item_id = int(item.get("id"))
        except Exception:
            self.error("Hata", "Geçersiz stok kartı.")
            _feedback("error")
            return

        try:
            current_on_hand = float(item.get("on_hand", 0) or 0)
            target_on_hand = float(target_qty)
        except Exception:
            self.error("Hata", "Hedef stok değeri geçersiz.")
            _feedback("error")
            return

        if target_on_hand < 0:
            self.error("Hata", "Hedef stok 0 veya daha büyük olmalı.")
            _feedback("error")
            return

        delta = target_on_hand - current_on_hand
        if abs(delta) < 1e-9:
            _feedback("idle")
            return

        move_qty = abs(delta)
        move_text = "Düzeltme Girişi" if delta > 0 else "Düzeltme Çıkışı"
        unit_cost: Optional[float] = None
        unit_cost_input_mode: Optional[str] = None
        unit_cost_vat_rate: Optional[float] = None
        currency = str(
            item.get("default_currency")
            or item.get("avg_cost_currency")
            or "TRY"
        ).strip().upper() or "TRY"

        if delta > 0:
            suggested_cost = item.get("default_cost")
            if suggested_cost is None:
                suggested_cost = item.get("avg_unit_cost")
            default_cost_text = ""
            try:
                if suggested_cost is not None:
                    default_cost_text = _fmt_num(float(suggested_cost), default="")
            except Exception:
                default_cost_text = ""

            cost_text, ok = QInputDialog.getText(
                self,
                "Birim Maliyet Zorunlu",
                (
                    "Hızlı giriş düzeltmesinde birim maliyet zorunludur.\n"
                    f"Lütfen birim maliyet gir ({currency}):"
                ),
                text=default_cost_text,
            )
            if not ok:
                _feedback("idle")
                return
            raw_cost = str(cost_text or "").strip().replace(",", ".")
            try:
                unit_cost = float(raw_cost)
            except Exception:
                self.error("Hata", "Birim maliyet sayısal bir değer olmalı (örn. 12.5).")
                _feedback("error")
                return
            if unit_cost <= 0:
                self.error("Hata", "Birim maliyet 0'dan büyük olmalı.")
                _feedback("error")
                return

            vat_mode_label, ok = QInputDialog.getItem(
                self,
                "Maliyet KDV Modu",
                "Girilen birim maliyet nasıl yorumlansın?",
                ["KDV Dahil", "KDV Hariç"],
                0,
                False,
            )
            if not ok:
                _feedback("idle")
                return
            unit_cost_input_mode = "net" if str(vat_mode_label or "").strip().casefold().endswith("hariç") else "gross"
            try:
                unit_cost_vat_rate = float(item.get("vat_rate")) if item.get("vat_rate") not in (None, "") else None
            except Exception:
                unit_cost_vat_rate = None
            if unit_cost_input_mode == "net" and unit_cost_vat_rate is None:
                self.error("Hata", "KDV hariç maliyet için stok kartında KDV oranı zorunlu.")
                _feedback("error")
                return

        cost_line = (
            f"Birim maliyet: {_fmt_num(unit_cost)} {currency}\n"
            if (delta > 0 and unit_cost is not None)
            else ""
        )
        cost_mode_line = (
            f"Maliyet modu: {'KDV Hariç' if unit_cost_input_mode == 'net' else 'KDV Dahil'}\n"
            if (delta > 0 and unit_cost is not None)
            else ""
        )
        warn_msg = (
            "Bu işlem stok giriş/çıkış ekranından yapılmadığı için otomatik olarak "
            "'Düzeltme' hareketi şeklinde kaydedilecektir.\n\n"
            f"Mevcut stok: {_fmt_num(current_on_hand)}\n"
            f"Hedef stok: {_fmt_num(target_on_hand)}\n"
            f"Oluşacak hareket: {_fmt_num(move_qty)} ({move_text})\n"
            f"{cost_line}"
            f"{cost_mode_line}"
            "Muhatap alanı boş bırakılacaktır.\n\n"
            "Devam etmek istiyor musun?"
        )
        if not self.confirm("Stok Düzeltme Onayı", warn_msg):
            _feedback("idle")
            return

        note = (
            f"Stok kartı hızlı düzeltme: {_fmt_num(current_on_hand)} -> {_fmt_num(target_on_hand)}"
        )
        res = action_adjust_item_stock_to(
            item_id=item_id,
            target_qty=target_on_hand,
            note=note,
            created_by="stock_cards_inline_adjust",
            unit_cost=unit_cost,
            unit_cost_input_mode=unit_cost_input_mode,
            unit_cost_vat_rate=unit_cost_vat_rate,
            currency=currency,
        )
        if not res.success:
            self.error("Hata", f"{res.message}\n{res.data}")
            _feedback("error")
            return

        _feedback("success")
        keep_bulk_ids = self.items_list.bulk_selected_ids()
        self.refresh_table(keep_selected_id=item_id, keep_bulk_selected_ids=keep_bulk_ids)

    # ---------- actions ----------
    def save_or_update(self):
        sku = (self.le_sku.text() or "").strip()
        name = (self.le_name.text() or "").strip()
        if not sku or not name:
            self.error("Hata", "SKU ve Ad zorunlu.")
            return

        barcode_text = (self.le_barcode.text() or "").strip()

        item_files = self.item_file_picker.files()
        payload = {
            "sku": sku,
            "name": name,
            "barcode": barcode_text or None,
            "item_type": self.cb_item_type.currentData(),
            "unit": (self.cb_unit.currentText() or "adet").strip(),
            "brand": (self.cb_brand.currentText() or "").strip() or None,
            "category": (self.cb_category.currentText() or "").strip() or None,
            "sub_category": (self.cb_sub_category.currentText() or "").strip() or None,
            "model_code": (self.le_model_code.text() or "").strip() or None,
            "manufacturer": (self.le_manufacturer.text() or "").strip() or None,
            "gtip_code": (self.le_gtip_code.text() or "").strip() or None,
            "custom_label": (self.le_custom_label.text() or "").strip() or None,
            "location_code": (self.le_location_code.text() or "").strip() or None,
            "image_path": json.dumps(item_files) if item_files else None,
            "description": (self.te_description.toPlainText() or "").strip() or None,
            "note": (self.te_note.toPlainText() or "").strip() or None,
            "is_active": bool(self.chk_active.isChecked()),
            "min_stock": int(self.sp_min_stock.value()),
            "max_stock": int(self.sp_max_stock.value()) or None,
            "safety_stock": int(self.sp_safety_stock.value()) or None,
            "reorder_point": int(self.sp_reorder_point.value()) or None,
            "reorder_qty": int(self.sp_reorder_qty.value()) or None,
            "lead_time_days": int(self.sp_lead_time_days.value()) or None,
            "shelf_life_days": int(self.sp_shelf_life_days.value()) or None,
            "serial_tracking": bool(self.chk_serial_tracking.isChecked()),
            "lot_tracking": bool(self.chk_lot_tracking.isChecked()),
            "allow_negative_stock": bool(self.chk_allow_negative_stock.isChecked()),
            "vat_rate": float(self.le_vat_rate.value()) if self.le_vat_rate.has_value() else None,
            "weight_kg": float(self.le_weight.value()) if self.le_weight.has_value() else None,
            "length_cm": float(self.le_len.value()) if self.le_len.has_value() else None,
            "width_cm": float(self.le_wid.value()) if self.le_wid.has_value() else None,
            "height_cm": float(self.le_hei.value()) if self.le_hei.has_value() else None,
        }

        pk_txt = (self.le_id.text() or "").strip()
        res = action_update_item(pk=int(pk_txt), update_data=payload) if pk_txt else action_create_item(**payload)

        if res.success:
            self.info("OK", res.message or "İşlem başarılı.")
            keep_bulk_ids = self.items_list.bulk_selected_ids()
            if pk_txt:
                current_id = int(pk_txt)
                self.refresh_table(keep_selected_id=current_id, keep_bulk_selected_ids=keep_bulk_ids)
                self._set_left_mode("edit")
                self.items_list.set_selected_id(current_id)
                self._open_editor_panel()
            else:
                self.refresh_table(keep_bulk_selected_ids=keep_bulk_ids)
                self._open_new_form()
        else:
            self.error("Hata", f"{res.message}\n{res.data}")

    def delete_item(self):
        pk_txt = (self.le_id.text() or "").strip()
        if not pk_txt:
            self.error("Hata", "Silmek için listeden bir kart seç.")
            return

        if not self.confirm("Silme Onay", "Bu stok kart silinecek. Emin misin?"):
            return

        pk = int(pk_txt)
        keep_bulk_ids = [bid for bid in self.items_list.bulk_selected_ids() if int(bid) != pk]
        res = action_delete_item(pk=pk, cascade=False)
        if res.success:
            self.info("OK", res.message or "Silindi.")
            self.refresh_table(keep_bulk_selected_ids=keep_bulk_ids)
            self._close_editor_panel()
            return

        # Bağlı hareket varsa kullanıcıya cascade sor
        can_cascade = bool(res.data.get("can_cascade")) if isinstance(res.data, dict) else False
        if can_cascade and self.confirm(
            "Bağlı Hareketler Var",
            "Bu stok kartına bağlı hareketler bulunuyor. Tüm hareketleri de silip devam edelim mi?",
        ):
            res2 = action_delete_item(pk=pk, cascade=True)
            if res2.success:
                self.info("OK", res2.message or "Silindi.")
                self.refresh_table(keep_bulk_selected_ids=keep_bulk_ids)
                self._close_editor_panel()
                return
            self.error("Hata", res2.message or "Silme başarısız.")
            return

        self.error("Hata", res.message or "Silme başarısız.")


# =========================================================
# ? Warehouse Manager
# =========================================================








