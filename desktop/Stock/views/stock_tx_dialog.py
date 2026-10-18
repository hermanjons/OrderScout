from __future__ import annotations
from .views import *

def _stock_row_pk(record: Any) -> Optional[int]:
    if isinstance(record, dict):
        value = record.get("pk")
        if value in (None, ""):
            value = record.get("id")
    else:
        value = getattr(record, "pk", None)
        if value in (None, ""):
            value = getattr(record, "id", None)
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


class StockTxListModel(QAbstractListModel):
    TitleRole = Qt.ItemDataRole.UserRole + 101
    SubtitleRole = Qt.ItemDataRole.UserRole + 102
    ExtraRole = Qt.ItemDataRole.UserRole + 103
    DirectionRole = Qt.ItemDataRole.UserRole + 104
    TxRole = Qt.ItemDataRole.UserRole + 105
    SelectedRole = Qt.ItemDataRole.UserRole + 106
    PlaceholderRole = Qt.ItemDataRole.UserRole + 107
    ActiveRole = Qt.ItemDataRole.UserRole + 108
    BulkSelectedRole = Qt.ItemDataRole.UserRole + 109
    ItemImageRole = Qt.ItemDataRole.UserRole + 110

    def __init__(self, txs: list | None = None, parent=None, *, on_selection_changed=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._has_placeholder = False
        self._on_selection_changed = on_selection_changed
        self._active_row: int = -1
        self._bulk_selected_rows: set[int] = set()
        self._row_by_id: dict[int, int] = {}
        self.set_items(txs or [])

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
        if role == self.DirectionRole:
            return item.get("direction") or ""
        if role == self.TxRole:
            return item.get("tx")
        if role == self.SelectedRole:
            return row == self._active_row
        if role == self.PlaceholderRole:
            return False
        if role == self.ActiveRole:
            return row == self._active_row
        if role == self.BulkSelectedRole:
            return row in self._bulk_selected_rows
        if role == self.ItemImageRole:
            return item.get("item_image_path") or ""
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled

    @staticmethod
    def _safe_tx_id(value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    @classmethod
    def _tx_id_of(cls, tx: Any) -> Optional[int]:
        return cls._safe_tx_id(_stock_row_pk(tx))

    def set_items(
        self,
        txs: list,
        *,
        selected_id: Optional[int] = None,
        bulk_selected_ids: Optional[list[int]] = None,
        item_name_by_id: Optional[dict[int, str]] = None,
        item_unit_by_id: Optional[dict[int, str]] = None,
        item_image_by_id: Optional[dict[int, str]] = None,
        warehouse_name_by_id: Optional[dict[int, str]] = None,
    ) -> None:
        keep_selected_id = self._safe_tx_id(selected_id)
        keep_bulk_ids = {
            bid for bid in (self._safe_tx_id(v) for v in (bulk_selected_ids or []))
            if bid is not None
        }
        item_name_by_id = item_name_by_id or {}
        item_unit_by_id = item_unit_by_id or {}
        item_image_by_id = item_image_by_id or {}
        warehouse_name_by_id = warehouse_name_by_id or {}
        self.beginResetModel()
        if txs:
            rows: list[dict] = []
            active_row = -1
            bulk_rows: set[int] = set()
            row_by_id: dict[int, int] = {}
            for idx, tx in enumerate(txs):
                tx_id = self._tx_id_of(tx)
                if tx_id is not None:
                    row_by_id[tx_id] = idx
                tx_get = tx.get if isinstance(tx, dict) else lambda key, default=None: getattr(tx, key, default)
                direction_code = str(tx_get("direction", "") or "")
                direction_text = _human_tx_direction(direction_code)
                qty = _fmt_num(tx_get("qty", 0), default="0")
                occurred_at = tx_get("occurred_at", None)
                if isinstance(occurred_at, datetime):
                    occurred_text = occurred_at.strftime("%d.%m.%Y %H:%M")
                else:
                    occurred_text = str(occurred_at or "-")
                reason_text = _human_tx_reason(tx_get("reason", "") or "")
                item_id = tx_get("item_id", None)
                warehouse_id = tx_get("warehouse_id", None)
                try:
                    item_key = int(item_id)
                except Exception:
                    item_key = None
                item_name = item_name_by_id.get(item_key, f"#{item_id}" if item_id is not None else "-")
                item_unit = str(item_unit_by_id.get(item_key, "") or "").strip()
                qty_with_unit = f"{qty} {item_unit}".strip() if item_unit else qty
                wh_name = warehouse_name_by_id.get(warehouse_id, f"#{warehouse_id}" if warehouse_id is not None else "-")
                item_image_path = _first_image_path(item_image_by_id.get(item_key, ""))

                cost_text = _tx_unit_cost_text(tx)
                counterparty = str(tx_get("counterparty", "") or "").strip() or "-"
                note = _clean_tx_note_for_card(tx_get("note", "")) or "-"
                extra_parts = [f"Maliyet: {cost_text}", f"Muhatap: {counterparty}"]
                extra_parts.append(f"Not: {note}")

                if keep_selected_id is not None and tx_id == keep_selected_id:
                    active_row = idx
                if tx_id is not None and tx_id in keep_bulk_ids:
                    bulk_rows.add(idx)
                rows.append(
                    {
                        "tx": tx,
                        "title": f"{direction_text} • {qty_with_unit}",
                        "subtitle": f"Tarih: {occurred_text} | Sebep: {reason_text} | Ürün: {item_name} | Depo: {wh_name}",
                        "extra": " | ".join(extra_parts),
                        "direction": direction_code,
                        "item_image_path": item_image_path,
                    }
                )
            self._rows = rows
            self._has_placeholder = False
            self._active_row = active_row
            self._bulk_selected_rows = bulk_rows
            self._row_by_id = row_by_id
        else:
            self._rows = [{"placeholder": True, "title": STOCK_TX_EMPTY_TEXT}]
            self._has_placeholder = True
            self._active_row = -1
            self._bulk_selected_rows = set()
            self._row_by_id = {}
        self.endResetModel()

    def selected_tx(self):
        if self._has_placeholder or self._active_row < 0 or self._active_row >= len(self._rows):
            return None
        return self._rows[self._active_row].get("tx")

    def selected_tx_id(self) -> Optional[int]:
        tx = self.selected_tx()
        if tx is None:
            return None
        return self._tx_id_of(tx)

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

    def set_selected_by_id(self, tx_id: Optional[int]) -> bool:
        sid = self._safe_tx_id(tx_id)
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

    def bulk_selected_txs(self) -> list[Any]:
        out: list[Any] = []
        for row in sorted(self._bulk_selected_rows):
            if 0 <= row < len(self._rows):
                tx = self._rows[row].get("tx")
                if tx is not None:
                    out.append(tx)
        return out

    def bulk_selected_ids(self) -> list[int]:
        ids: list[int] = []
        for tx in self.bulk_selected_txs():
            sid = self._safe_tx_id(_stock_row_pk(tx))
            if sid is not None:
                ids.append(sid)
        return ids

    def bulk_selected_count(self) -> int:
        return len(self._bulk_selected_rows)


class StockTxListDelegate(RecordWorkspaceListDelegate):
    def __init__(
        self,
        parent=None,
        *,
        on_select_button=None,
        on_source_button=None,
        on_order_button=None,
        on_listing_button=None,
        on_image_click=None,
    ):
        super().__init__(parent, on_select_button=on_select_button)
        self._row_height = STOCK_MANAGER_CARD_ROW_HEIGHT
        self._hover_source_row: int | None = None
        self._pressed_source_row: int | None = None
        self._hover_order_row: int | None = None
        self._pressed_order_row: int | None = None
        self._hover_listing_row: int | None = None
        self._pressed_listing_row: int | None = None
        self._on_source_button = on_source_button
        self._on_order_button = on_order_button
        self._on_listing_button = on_listing_button
        self._on_image_click = on_image_click

    @staticmethod
    def _draw_labeled_line(
        painter: QPainter,
        rect: QRect,
        text: str,
        *,
        label_color: QColor,
        value_color: QColor,
        point_size: int = 8,
    ) -> None:
        parts = [str(p).strip() for p in str(text or "").split("|") if str(p).strip()]
        if not parts:
            return

        label_font = QFont(STOCK_CARD_FONT_FAMILY, point_size, QFont.Weight.Bold)
        value_font = QFont(STOCK_CARD_FONT_FAMILY, point_size, QFont.Weight.Normal)

        x = int(rect.left())
        right = int(rect.right())

        def _draw_piece(piece_text: str, font: QFont, color: QColor) -> bool:
            nonlocal x
            if not piece_text or x > right:
                return False
            remaining = max(0, right - x + 1)
            if remaining <= 0:
                return False
            painter.setFont(font)
            painter.setPen(color)
            fm = painter.fontMetrics()
            full_w = fm.horizontalAdvance(piece_text)
            draw_text = piece_text if full_w <= remaining else fm.elidedText(piece_text, Qt.TextElideMode.ElideRight, remaining)
            if not draw_text:
                return False
            draw_w = min(remaining, fm.horizontalAdvance(draw_text))
            painter.drawText(QRect(x, rect.top(), draw_w, rect.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, draw_text)
            x += draw_w
            return full_w <= remaining

        for idx, part in enumerate(parts):
            if idx > 0:
                if not _draw_piece(" | ", value_font, value_color):
                    break
            if ":" in part:
                key, value = part.split(":", 1)
                label_text = f"{key.strip()}: "
                value_text = value.strip()
                if not _draw_piece(label_text, label_font, label_color):
                    break
                if not _draw_piece(value_text, value_font, value_color):
                    break
            else:
                if not _draw_piece(part, value_font, value_color):
                    break

    def _is_placeholder_index(self, index: QModelIndex) -> bool:
        return bool(index.data(StockTxListModel.PlaceholderRole))

    def _is_selected_index(self, index: QModelIndex) -> bool:
        return bool(index.data(StockTxListModel.BulkSelectedRole))

    def _is_active_index(self, index: QModelIndex) -> bool:
        return bool(index.data(StockTxListModel.ActiveRole))

    def _is_hook_selected_index(self, index: QModelIndex) -> bool:
        return bool(index.data(StockTxListModel.BulkSelectedRole))

    def _button_rects(
        self,
        rect: QRect,
        *,
        direction_code: str,
        has_order_button: bool = False,
        has_listing_button: bool = False,
        view=None,
    ) -> tuple[QRect, Optional[QRect], Optional[QRect], Optional[QRect]]:
        left_margin = 8
        source_w = 112
        order_w = 84
        listing_w = 70
        gap = 8
        select_rect = self._build_hook_rect(
            rect,
            view=view,
            left_margin=left_margin,
            right_margin=10,
        )

        source_rect: Optional[QRect] = None
        order_rect: Optional[QRect] = None
        listing_rect: Optional[QRect] = None
        source_x = select_rect.left() - gap - source_w
        min_x = rect.left() + left_margin
        if source_x >= min_x:
            source_rect = QRect(source_x, select_rect.top(), source_w, select_rect.height())

            if has_order_button:
                order_x = source_rect.left() - gap - order_w
                if order_x >= min_x:
                    order_rect = QRect(order_x, select_rect.top(), order_w, select_rect.height())
            left_anchor = order_rect.left() if order_rect is not None else source_rect.left()
            if has_listing_button:
                listing_x = left_anchor - gap - listing_w
                if listing_x >= min_x:
                    listing_rect = QRect(listing_x, select_rect.top(), listing_w, select_rect.height())

        return select_rect, source_rect, order_rect, listing_rect

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = option.rect.adjusted(6, 4, -6, -4)
        row = index.row()
        is_placeholder = bool(index.data(StockTxListModel.PlaceholderRole))
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        active_flag = bool(index.data(StockTxListModel.ActiveRole))
        active_visible = active_flag and self._active_visual_enabled
        bulk_selected = bool(index.data(StockTxListModel.BulkSelectedRole))

        if is_placeholder:
            painter.setPen(QColor(STOCK_CARD_PLACEHOLDER_TEXT_COLOR))
            painter.setFont(QFont(STOCK_CARD_FONT_FAMILY, STOCK_CARD_PLACEHOLDER_FONT_SIZE))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, index.data(StockTxListModel.TitleRole) or "")
            painter.restore()
            return

        self._paint_card_surface(
            painter,
            rect,
            hovered=hovered,
            card_selected=bulk_selected,
            active_visible=active_visible,
        )

        direction_code = str(index.data(StockTxListModel.DirectionRole) or "")
        icon_path = str(index.data(StockTxListModel.ItemImageRole) or "").strip()

        x = rect.left() + 12
        image_rect = QRect(x, rect.center().y() - self._icon_size // 2, self._icon_size, self._icon_size)
        dpr = painter.device().devicePixelRatioF()
        pix = self._load_icon(icon_path, dpr)
        if pix is not None:
            pr = pix.devicePixelRatio() or 1.0
            pw = int(pix.width() / pr)
            ph = int(pix.height() / pr)
            target = QRect(0, 0, pw, ph)
            target.moveCenter(image_rect.center())
            painter.drawPixmap(target, pix)
        else:
            painter.setBrush(QColor(STOCK_CARD_ICON_PLACEHOLDER_COLOR))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(image_rect, 8, 8)

        direction_is_in = direction_code.endswith("IN") or direction_code.endswith("IN_") or direction_code == "IN"
        badge_color = QColor("#22C55E") if direction_is_in else QColor("#EF4444")
        badge_rect = QRect(image_rect.right() + 10, rect.center().y() - 22, 44, 44)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(240, 253, 244) if direction_is_in else QColor(254, 242, 242))
        painter.drawRoundedRect(badge_rect, 12, 12)
        painter.setBrush(badge_color)
        painter.drawEllipse(badge_rect.center(), 8, 8)

        x = badge_rect.right() + 12
        tx_payload = index.data(StockTxListModel.TxRole)
        show_order_button = _is_order_out_tx(tx_payload)
        show_listing_button = _has_listing_ref_tx(tx_payload)
        select_rect, source_rect, order_rect, listing_rect = self._button_rects(
            rect,
            direction_code=direction_code,
            has_order_button=show_order_button,
            has_listing_button=show_listing_button,
            view=option.widget,
        )
        button_lefts = [select_rect.left()]
        if source_rect is not None:
            button_lefts.append(source_rect.left())
        if order_rect is not None:
            button_lefts.append(order_rect.left())
        if listing_rect is not None:
            button_lefts.append(listing_rect.left())
        text_right = min(button_lefts) - 10
        text_width = max(10, text_right - x)

        title = index.data(StockTxListModel.TitleRole) or ""
        subtitle = index.data(StockTxListModel.SubtitleRole) or ""
        extra = index.data(StockTxListModel.ExtraRole) or ""

        painter.setPen(QColor(STOCK_CARD_TITLE_COLOR))
        painter.setFont(QFont(STOCK_CARD_FONT_FAMILY, STOCK_CARD_TITLE_FONT_SIZE, QFont.Weight.Bold))
        title_rect = QRect(x, rect.top() + 10, text_width, 20)
        fm = painter.fontMetrics()
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(title, Qt.TextElideMode.ElideRight, title_rect.width()),
        )

        sub_rect = QRect(x, title_rect.bottom() + 4, text_width, 18)
        self._draw_labeled_line(
            painter,
            sub_rect,
            subtitle,
            label_color=QColor(STOCK_CARD_TITLE_COLOR),
            value_color=QColor(STOCK_CARD_BODY_COLOR),
            point_size=8,
        )

        extra_rect = QRect(x, sub_rect.bottom() + 2, text_width, 18)
        self._draw_labeled_line(
            painter,
            extra_rect,
            extra,
            label_color=QColor(STOCK_CARD_TITLE_COLOR),
            value_color=QColor(STOCK_CARD_BODY_COLOR),
            point_size=8,
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
            painter.drawText(source_rect, Qt.AlignmentFlag.AlignCenter, STOCK_TX_SOURCE_BUTTON_TEXT)

        if order_rect is not None:
            hover_order = self._hover_order_row == row
            pressed_order = self._pressed_order_row == row
            order_draw = order_rect
            if pressed_order:
                order_draw = order_rect.adjusted(1, 1, -1, -1)
                painter.setBrush(QColor(STOCK_CARD_SELECTED_BUTTON_FILL_COLOR))
                painter.setPen(QPen(QColor(STOCK_CARD_SELECTED_BUTTON_BORDER_COLOR), 1))
            elif hover_order:
                painter.setBrush(QColor(STOCK_CARD_HOVER_BUTTON_FILL_COLOR))
                painter.setPen(QPen(QColor(STOCK_CARD_HOVER_BUTTON_BORDER_COLOR), 1))
            else:
                painter.setBrush(QColor(STOCK_CARD_IDLE_BUTTON_FILL_COLOR))
                painter.setPen(QPen(QColor(STOCK_CARD_IDLE_BUTTON_BORDER_COLOR), 1))
            painter.drawRoundedRect(order_draw, 8, 8)
            painter.setPen(QColor(STOCK_CARD_ACTION_TEXT_COLOR))
            painter.setFont(QFont(STOCK_CARD_FONT_FAMILY, STOCK_CARD_ACTION_FONT_SIZE, QFont.Weight.Bold))
            painter.drawText(order_rect, Qt.AlignmentFlag.AlignCenter, STOCK_TX_ORDER_BUTTON_TEXT)

        if listing_rect is not None:
            hover_listing = self._hover_listing_row == row
            pressed_listing = self._pressed_listing_row == row
            listing_draw = listing_rect
            if pressed_listing:
                listing_draw = listing_rect.adjusted(1, 1, -1, -1)
                painter.setBrush(QColor(STOCK_CARD_SELECTED_BUTTON_FILL_COLOR))
                painter.setPen(QPen(QColor(STOCK_CARD_SELECTED_BUTTON_BORDER_COLOR), 1))
            elif hover_listing:
                painter.setBrush(QColor(STOCK_CARD_HOVER_BUTTON_FILL_COLOR))
                painter.setPen(QPen(QColor(STOCK_CARD_HOVER_BUTTON_BORDER_COLOR), 1))
            else:
                painter.setBrush(QColor(STOCK_CARD_IDLE_BUTTON_FILL_COLOR))
                painter.setPen(QPen(QColor(STOCK_CARD_IDLE_BUTTON_BORDER_COLOR), 1))
            painter.drawRoundedRect(listing_draw, 8, 8)
            painter.setPen(QColor(STOCK_CARD_ACTION_TEXT_COLOR))
            painter.setFont(QFont(STOCK_CARD_FONT_FAMILY, STOCK_CARD_ACTION_FONT_SIZE, QFont.Weight.Bold))
            painter.drawText(listing_rect, Qt.AlignmentFlag.AlignCenter, STOCK_TX_LISTING_BUTTON_TEXT)

        self._paint_hook_button(
            painter,
            select_rect,
            index=index,
            row=row,
            hook_selected=bulk_selected,
        )

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if bool(index.data(StockTxListModel.PlaceholderRole)):
            return False
        rect = option.rect.adjusted(6, 4, -6, -4)
        view = option.widget
        direction_code = str(index.data(StockTxListModel.DirectionRole) or "")
        image_rect = QRect(
            rect.left() + 12,
            rect.center().y() - self._icon_size // 2,
            self._icon_size,
            self._icon_size,
        )
        tx_payload = index.data(StockTxListModel.TxRole)
        show_order_button = _is_order_out_tx(tx_payload)
        show_listing_button = _has_listing_ref_tx(tx_payload)
        select_rect, source_rect, order_rect, listing_rect = self._button_rects(
            rect,
            direction_code=direction_code,
            has_order_button=show_order_button,
            has_listing_button=show_listing_button,
            view=view,
        )

        def _clear_hover_state() -> bool:
            changed = False
            if self._hover_row == index.row():
                self._hover_row = None
                changed = True
            if self._hover_source_row == index.row():
                self._hover_source_row = None
                changed = True
            if self._hover_order_row == index.row():
                self._hover_order_row = None
                changed = True
            if self._hover_listing_row == index.row():
                self._hover_listing_row = None
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
            if self._pressed_order_row == index.row():
                self._pressed_order_row = None
                changed = True
            if self._pressed_listing_row == index.row():
                self._pressed_listing_row = None
                changed = True
            return changed

        if event.type() == QEvent.Type.MouseMove:
            pos = event.position().toPoint()
            hovering_image = image_rect.contains(pos)
            hovering_select = select_rect.contains(pos)
            hovering_source = bool(source_rect is not None and source_rect.contains(pos))
            hovering_order = bool(order_rect is not None and order_rect.contains(pos))
            hovering_listing = bool(listing_rect is not None and listing_rect.contains(pos))
            changed = False
            if hovering_image:
                changed = _clear_hover_state()
            elif hovering_select:
                if self._hover_row != index.row():
                    self._hover_row = index.row()
                    changed = True
                if self._hover_source_row == index.row():
                    self._hover_source_row = None
                    changed = True
                if self._hover_order_row == index.row():
                    self._hover_order_row = None
                    changed = True
                if self._hover_listing_row == index.row():
                    self._hover_listing_row = None
                    changed = True
            elif hovering_source:
                if self._hover_source_row != index.row():
                    self._hover_source_row = index.row()
                    changed = True
                if self._hover_row == index.row():
                    self._hover_row = None
                    changed = True
                if self._hover_order_row == index.row():
                    self._hover_order_row = None
                    changed = True
                if self._hover_listing_row == index.row():
                    self._hover_listing_row = None
                    changed = True
            elif hovering_order:
                if self._hover_order_row != index.row():
                    self._hover_order_row = index.row()
                    changed = True
                if self._hover_row == index.row():
                    self._hover_row = None
                    changed = True
                if self._hover_source_row == index.row():
                    self._hover_source_row = None
                    changed = True
                if self._hover_listing_row == index.row():
                    self._hover_listing_row = None
                    changed = True
            elif hovering_listing:
                if self._hover_listing_row != index.row():
                    self._hover_listing_row = index.row()
                    changed = True
                if self._hover_row == index.row():
                    self._hover_row = None
                    changed = True
                if self._hover_source_row == index.row():
                    self._hover_source_row = None
                    changed = True
                if self._hover_order_row == index.row():
                    self._hover_order_row = None
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
            if self._hover_order_row is not None:
                self._hover_order_row = None
                changed = True
            if self._hover_listing_row is not None:
                self._hover_listing_row = None
                changed = True
            if changed and view:
                view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if image_rect.contains(pos):
                return True
            if source_rect is not None and source_rect.contains(pos):
                self._pressed_source_row = index.row()
                if view:
                    view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
                return True
            if order_rect is not None and order_rect.contains(pos):
                self._pressed_order_row = index.row()
                if view:
                    view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
                return True
            if listing_rect is not None and listing_rect.contains(pos):
                self._pressed_listing_row = index.row()
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
            if image_rect.contains(pos):
                tx = index.data(StockTxListModel.TxRole)
                if callable(self._on_image_click):
                    try:
                        self._on_image_click(index, tx)
                    except Exception:
                        pass
                return True
            select_was_pressed = self._pressed_row == index.row()
            source_was_pressed = self._pressed_source_row == index.row()
            order_was_pressed = self._pressed_order_row == index.row()
            listing_was_pressed = self._pressed_listing_row == index.row()
            _clear_pressed_state()
            if view:
                view.viewport().update(option.rect.adjusted(-2, -2, 2, 2))
            if source_was_pressed and source_rect is not None and source_rect.contains(pos):
                if view is not None and hasattr(view, "_mark_action_button_click_handled"):
                    view._mark_action_button_click_handled()
                if callable(self._on_source_button):
                    try:
                        self._on_source_button(index)
                    except Exception:
                        pass
                return True
            if order_was_pressed and order_rect is not None and order_rect.contains(pos):
                if view is not None and hasattr(view, "_mark_action_button_click_handled"):
                    view._mark_action_button_click_handled()
                if callable(self._on_order_button):
                    try:
                        self._on_order_button(index)
                    except Exception:
                        pass
                return True
            if listing_was_pressed and listing_rect is not None and listing_rect.contains(pos):
                if view is not None and hasattr(view, "_mark_action_button_click_handled"):
                    view._mark_action_button_click_handled()
                if callable(self._on_listing_button):
                    try:
                        self._on_listing_button(index)
                    except Exception:
                        pass
                return True
            if select_was_pressed and select_rect.contains(pos):
                self._mark_view_action_click_handled(view)
                is_selected = bool(index.data(StockTxListModel.BulkSelectedRole))
                next_selected = not is_selected
                return bool(self._handle_hook_activated(model, index, next_selected))
        return super().editorEvent(event, model, option, index)

    def sizeHint(self, option: QStyleOptionViewItem, _index: QModelIndex) -> QSize:
        _ = option
        return QSize(0, self._row_height)


class StockTxListWidget(QListView):
    selection_changed = pyqtSignal()
    page_changed = pyqtSignal(int, int, int, int)
    tx_selected = pyqtSignal(object)
    tx_clicked = pyqtSignal(object)
    record_clicked = pyqtSignal(object)
    selection_button_clicked = pyqtSignal(object, bool)
    source_button_clicked = pyqtSignal(object)
    order_button_clicked = pyqtSignal(object)
    listing_button_clicked = pyqtSignal(object)
    image_clicked = pyqtSignal(object)
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
        self._action_button_click_handled = False
        self._active_spin_allowed: bool = True
        self._active_border_animation_enabled: bool = False
        self._guide_select_animation_enabled: bool = False
        self._external_selection_handler_enabled: bool = False
        self._last_selection_signature: tuple[str, ...] = tuple()
        self._all_txs: list[Any] = []
        self._active_tx_id: Optional[int] = None
        self._bulk_selected_ids: set[int] = set()
        self._item_name_by_id: dict[int, str] = {}
        self._item_unit_by_id: dict[int, str] = {}
        self._item_image_by_id: dict[int, str] = {}
        self._warehouse_name_by_id: dict[int, str] = {}
        self.page_size: int = 20
        self.current_page: int = 1

        self._model = StockTxListModel(parent=self, on_selection_changed=self._emit_selected)
        self._delegate = StockTxListDelegate(
            self,
            on_select_button=self._on_select_button_clicked,
            on_source_button=self._on_source_button_clicked,
            on_order_button=self._on_order_button_clicked,
            on_listing_button=self._on_listing_button_clicked,
            on_image_click=self._on_image_clicked,
        )
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self.clicked.connect(self._on_clicked)

        self._active_border_timer = QTimer(self)
        self._active_border_timer.setInterval(42)
        self._active_border_timer.timeout.connect(self._tick_active_border_animation)

    def _mark_action_button_click_handled(self) -> None:
        self._action_button_click_handled = True

    def _on_select_button_clicked(self, index: QModelIndex, selected: bool) -> bool:
        if not index.isValid():
            return False
        if bool(index.data(StockTxListModel.PlaceholderRole)):
            return False
        tx = index.data(StockTxListModel.TxRole)
        if not self._external_selection_handler_enabled:
            self.set_record_selected(tx, bool(selected))
        self.selection_button_clicked.emit(tx, bool(selected))
        return True

    def _on_source_button_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        if bool(index.data(StockTxListModel.PlaceholderRole)):
            return
        tx = index.data(StockTxListModel.TxRole)
        self.source_button_clicked.emit(tx)

    def _on_order_button_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        if bool(index.data(StockTxListModel.PlaceholderRole)):
            return
        tx = index.data(StockTxListModel.TxRole)
        self.order_button_clicked.emit(tx)

    def _on_listing_button_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        if bool(index.data(StockTxListModel.PlaceholderRole)):
            return
        tx = index.data(StockTxListModel.TxRole)
        self.listing_button_clicked.emit(tx)

    def _on_image_clicked(self, index: QModelIndex, tx: Any) -> None:
        if not index.isValid():
            return
        if bool(index.data(StockTxListModel.PlaceholderRole)):
            return
        self.set_selected_id(self._tx_id_of(tx))
        self.image_clicked.emit(tx)

    def _on_clicked(self, index: QModelIndex) -> None:
        if self._action_button_click_handled:
            self._action_button_click_handled = False
            return
        if not index.isValid():
            return
        if bool(index.data(StockTxListModel.PlaceholderRole)):
            self.background_clicked.emit()
            self.blank_area_clicked.emit()
            return
        tx = index.data(StockTxListModel.TxRole)
        self.tx_clicked.emit(tx)
        self.record_clicked.emit(tx)
        self.set_selected_id(self._tx_id_of(tx))

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
        return tuple(str(tx_id) for tx_id in sorted(self._bulk_selected_ids))

    def _emit_selection_state_if_needed(self, *, force: bool = False) -> None:
        signature = self._selection_signature()
        if not force and signature == self._last_selection_signature:
            return
        self._last_selection_signature = signature
        self.selection_state_changed.emit()

    def _emit_selected(self) -> None:
        active_row = self._model.active_row()
        self._set_active_border_animation_enabled(active_row >= 0 and self._active_spin_allowed)
        self.tx_selected.emit(self.selected_tx())
        self._emit_selection_state_if_needed()
        self.selection_changed.emit()
        self.bulk_selection_changed.emit(self.bulk_selected_count())
        self.page_changed.emit(self.current_page, self.get_total_pages(), self.total_record_count(), self.shown_count())

    @classmethod
    def _tx_id_of(cls, tx: Any) -> Optional[int]:
        return StockTxListModel._tx_id_of(tx)

    def set_items(
        self,
        txs: list,
        *,
        keep_selected_id: Optional[int] = None,
        keep_bulk_selected_ids: Optional[list[int]] = None,
        item_name_by_id: Optional[dict[int, str]] = None,
        item_unit_by_id: Optional[dict[int, str]] = None,
        item_image_by_id: Optional[dict[int, str]] = None,
        warehouse_name_by_id: Optional[dict[int, str]] = None,
    ) -> None:
        selected_id = keep_selected_id if keep_selected_id is not None else self.selected_tx_id()
        bulk_ids = keep_bulk_selected_ids if keep_bulk_selected_ids is not None else self.bulk_selected_ids()
        self._all_txs = txs if isinstance(txs, list) else list(txs or [])
        self._item_name_by_id = item_name_by_id or {}
        self._item_unit_by_id = item_unit_by_id or {}
        self._item_image_by_id = item_image_by_id or {}
        self._warehouse_name_by_id = warehouse_name_by_id or {}
        normalized_selected_id = self._tx_id_of({"id": selected_id}) if selected_id is not None else None
        selected_ids = {
            tx_id for tx_id in (self._tx_id_of({"id": value}) for value in (bulk_ids or []))
            if tx_id is not None
        }
        if normalized_selected_id is not None or selected_ids:
            available_ids = {
                tx_id for tx_id in (self._tx_id_of(tx) for tx in self._all_txs)
                if tx_id is not None
            }
            self._active_tx_id = normalized_selected_id if normalized_selected_id in available_ids else None
            self._bulk_selected_ids = {tx_id for tx_id in selected_ids if tx_id in available_ids}
        else:
            self._active_tx_id = None
            self._bulk_selected_ids = set()
        self.current_page = 1
        self._build_page()

    def _page_bounds(self) -> tuple[int, int]:
        page_size = max(1, int(self.page_size or 20))
        total = len(self._all_txs or [])
        total_pages = max(1, (total + page_size - 1) // page_size)
        self.current_page = max(1, min(int(self.current_page or 1), total_pages))
        start = (self.current_page - 1) * page_size
        return start, min(start + page_size, total)

    def _current_page_txs(self) -> list[Any]:
        start, end = self._page_bounds()
        return (self._all_txs or [])[start:end]

    def _build_page(self) -> None:
        self._model.set_items(
            self._current_page_txs(),
            selected_id=self._active_tx_id,
            bulk_selected_ids=list(self._bulk_selected_ids),
            item_name_by_id=self._item_name_by_id,
            item_unit_by_id=self._item_unit_by_id,
            item_image_by_id=self._item_image_by_id,
            warehouse_name_by_id=self._warehouse_name_by_id,
        )
        self.scrollToTop()
        self._emit_selected()

    def set_selected_id(self, tx_id: Optional[int]) -> bool:
        self._active_tx_id = self._tx_id_of({"id": tx_id}) if tx_id is not None else None
        ok = self._model.set_selected_by_id(self._active_tx_id)
        self._emit_selected()
        return ok

    def set_external_selection_handler_enabled(self, enabled: bool) -> None:
        self._external_selection_handler_enabled = bool(enabled)

    def set_record_selected(self, record, selected: bool) -> None:
        tx_id = self._tx_id_of(record)
        if tx_id is None:
            return
        if selected:
            self._bulk_selected_ids.add(tx_id)
        else:
            self._bulk_selected_ids.discard(tx_id)
        for row in range(self._model.rowCount()):
            idx = self._model.index(row)
            tx = idx.data(StockTxListModel.TxRole)
            if self._tx_id_of(tx) != tx_id:
                continue
            self._model.set_bulk_selected_row(row, bool(selected))
            return
        self._emit_selected()

    def selected_tx(self):
        active_id = self._active_tx_id
        if active_id is None:
            return None
        for tx in self._all_txs or []:
            if self._tx_id_of(tx) == active_id:
                return tx
        return None

    def selected_tx_id(self) -> Optional[int]:
        return self._active_tx_id

    def clear_selection(self) -> None:
        self.clear_active_selection()
        self._emit_selected()

    def clear_active_selection(self) -> None:
        self._active_tx_id = None
        self._model.clear_active_row()
        self._emit_selected()

    def clear_bulk_selection(self) -> None:
        self._bulk_selected_ids.clear()
        self._model.clear_bulk_selected_rows()
        self._emit_selected()

    def get_selected_records(self) -> list[Any]:
        return self.bulk_selected_txs()

    def bulk_selected_txs(self) -> list[Any]:
        selected_ids = set(self._bulk_selected_ids)
        return [
            tx for tx in (self._all_txs or [])
            if self._tx_id_of(tx) in selected_ids
        ]

    def bulk_selected_ids(self) -> list[int]:
        return sorted(self._bulk_selected_ids)

    def bulk_selected_count(self) -> int:
        return len(self._bulk_selected_ids)

    def total_record_count(self) -> int:
        return len(self._all_txs)

    def shown_count(self) -> int:
        return self._model.rowCount()

    def get_total_pages(self) -> int:
        total = len(self._all_txs or [])
        if total <= 0:
            return 1
        page_size = max(1, int(self.page_size or 20))
        return (total + page_size - 1) // page_size

    def set_page_size(self, size: int) -> None:
        self.page_size = max(1, int(size or 20))
        self.current_page = 1
        self._build_page()

    def next_page(self) -> None:
        self.go_to_page(self.current_page + 1)

    def prev_page(self) -> None:
        self.go_to_page(self.current_page - 1)

    def go_to_page(self, page: int) -> None:
        self.current_page = max(1, min(int(page or 1), self.get_total_pages()))
        self._build_page()

    def clear_selected_records(self) -> None:
        self.clear_bulk_selection()

    def select_all_filtered_records(self) -> None:
        all_ids = {
            tx_id for tx_id in (self._tx_id_of(tx) for tx in (self._all_txs or []))
            if tx_id is not None
        }
        if all_ids - self._bulk_selected_ids:
            self._bulk_selected_ids.update(all_ids)
            self._build_page()
        else:
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_dynamic_row_width()

    def sync_dynamic_row_width(self) -> None:
        try:
            self.doItemsLayout()
            self.viewport().update()
        except Exception:
            return

class StockTxWorkspaceBehaviorAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, dialog: "StockTxDialog") -> None:
        self.dialog = dialog

    @property
    def list_widget(self):
        return self.dialog.txs_list

    def get_mode(self) -> str:
        return str(self.dialog._left_mode or "edit")

    def set_mode(self, mode: str) -> None:
        self.dialog._set_left_mode(mode)

    def get_active_key(self) -> str:
        return str(self.dialog.txs_list.selected_tx_id() or "")

    def get_selected_count(self) -> int:
        return int(self.dialog.txs_list.bulk_selected_count() or 0)

    def get_record_key(self, record) -> str:
        return str(_stock_row_pk(record) or "")

    def prepare_new(self) -> None:
        self.dialog._prepare_new_tx_workspace()

    def activate_record(self, record) -> None:
        self.dialog.txs_list.set_selected_id(_stock_row_pk(record))

    def clear_active(self) -> None:
        self.dialog._clear_tx_workspace_state()

    def apply_selection(self, record, selected: bool) -> None:
        self.dialog.txs_list.set_record_selected(record, bool(selected))

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self.dialog.txs_list.set_select_button_guide_enabled(bool(enabled))

    def on_state_changed(self) -> None:
        self.dialog._sync_tx_workspace_state()

    def edit_guidance_message(self) -> str:
        return "Düzenlemek için sağdaki listeden bir hareket seç."

    def bulk_guidance_message(self) -> str:
        return "Toplu işlem için sağdaki listeden en az bir hareketi SEÇ ile işaretle."


__all__ = [name for name in globals() if not name.startswith("__")]

from .stock_item_manager_dialog import ImagePreviewDialog


class StockTxDialog(FullscreenDialog):
    MODE_IN = "IN"
    MODE_OUT = "OUT"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Stok Giriş / Çıkış")
        self._left_mode = "edit"
        self._tx_mode = self.MODE_IN
        self._item_name_by_id: dict[int, str] = {}
        self._item_unit_by_id: dict[int, str] = {}
        self._item_image_by_id: dict[int, str] = {}
        self._item_allow_negative_by_id: dict[int, bool] = {}
        self._item_vat_rate_by_id: dict[int, float | None] = {}
        self._warehouse_name_by_id: dict[int, str] = {}
        self._tx_image_preview: ImagePreviewDialog | None = None
        self._has_loaded_once = False
        self._forced_tx_ids: Optional[set[int]] = None
        self._forced_item_id: Optional[int] = None
        self._forced_tx_filter_note: str = ""
        self._out_avg_cost_suggestion: Optional[float] = None
        self._out_avg_currency_suggestion: str = "TRY"
        self._tx_query_cache_key: Optional[tuple[Any, ...]] = None
        self._tx_query_cache_records: list = []
        self._tx_refresh_suppressed = False
        self._signal_refresh_queued = False
        self._pending_signal_tx_id: Optional[int] = None
        self._listing_from_tx_window = None
        self._orders_from_tx_window = None
        self._tx_refresh_timer = QTimer(self)
        self._tx_refresh_timer.setSingleShot(True)
        self._tx_refresh_timer.setInterval(140)
        self._tx_refresh_timer.timeout.connect(self.refresh_txs_list)
        stock_signals.tx_created.connect(self._on_tx_created_signal)
        stock_signals.refreshed.connect(self._on_stock_domain_refreshed)
        self._form_reason_options = {
            self.MODE_IN: [
                (StockTxReason.manual_in.value, "Manuel Giriş"),
                (StockTxReason.adjustment.value, "Düzeltme"),
                (StockTxReason.return_in.value, "İade Giriş"),
            ],
            self.MODE_OUT: [
                (StockTxReason.manual_out.value, "Manuel Çıkış"),
                (StockTxReason.adjustment.value, "Düzeltme"),
                (StockTxReason.order_out.value, "Sipariş Çıkış"),
            ],
        }
        self._all_reason_options = [
            (StockTxReason.manual_in.value, "Manuel Giriş"),
            (StockTxReason.manual_out.value, "Manuel Çıkış"),
            (StockTxReason.adjustment.value, "Düzeltme"),
            (StockTxReason.return_in.value, "İade Giriş"),
            (StockTxReason.order_out.value, "Sipariş Çıkış"),
        ]

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
            left_subtitle="Düzenlemek için sağdaki listeden bir hareket seç.",
            filters_title=STOCK_MANAGER_FILTERS_TITLE,
            records_title="Hareket Listesi",
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
            style_sheet=None,
            shell_kwargs={**STOCK_MANAGER_WORKSPACE_SHELL_KWARGS, "left_stick_size": 760, "left_collapse_trigger": max(1, int(760 * 0.5)), "min_left_width": 340},
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": "Yeni işlem paneli",
                    "icon_path": str(ASSETS_DIR / "yeni-kayit.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": "İşlem düzenleme paneli",
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
        self._tx_splitter = splitter
        self._left_stick_size = 760
        self._left_card = self._workspace.left_card
        self.left_panel_title = self._workspace.left_card.title_label
        self.left_panel_hint = self._workspace.left_card.subtitle_label
        self._editor_scroll = self._workspace.editor_scroll
        self._editor_actions_wrap = self._workspace.editor_actions_host
        self._tx_form_scroll = self._editor_scroll
        self.bulk_panel = self._workspace.bulk_panel

        editor_host = QWidget(self._workspace.editor_host)
        editor_host.setObjectName("FormBody")
        left_layout = QVBoxLayout(editor_host)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        tabs_frame = QFrame()
        tabs_frame.setObjectName("TxModeTabs")
        self._tx_tabs_frame = tabs_frame
        tabs_layout = QHBoxLayout(tabs_frame)
        tabs_layout.setContentsMargins(6, 6, 6, 6)
        tabs_layout.setSpacing(8)

        self.btn_tab_in = QPushButton("Stok Giriş")
        self.btn_tab_in.setObjectName("TxModeTab")
        self.btn_tab_in.setProperty("tone", "in")
        self.btn_tab_in.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_in.clicked.connect(lambda: self._request_tx_mode(self.MODE_IN))

        self.btn_tab_out = QPushButton("Stok Çıkış")
        self.btn_tab_out.setObjectName("TxModeTab")
        self.btn_tab_out.setProperty("tone", "out")
        self.btn_tab_out.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_out.clicked.connect(lambda: self._request_tx_mode(self.MODE_OUT))

        tabs_layout.addWidget(self.btn_tab_in, 1)
        tabs_layout.addWidget(self.btn_tab_out, 1)
        left_layout.addWidget(self._tx_tabs_frame)

        self.lbl_mode_hint = QLabel("", objectName="SubTitle")
        self.lbl_mode_hint.setContentsMargins(2, 0, 2, 2)
        left_layout.addWidget(self.lbl_mode_hint)

        form_host = QWidget()
        form_host.setObjectName("FormBody")
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 6, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.cb_item = SwitchSelectWidget(multi=False, all_text="Seçiniz")
        self.btn_item_manage = _inline_action_btn("Stok Kartları", min_h=38, min_w=126)
        self.btn_item_manage.clicked.connect(self._open_item_manager)
        self.cb_wh = SwitchSelectWidget(multi=False, all_text="Seçiniz")
        self.btn_wh_manage = _inline_action_btn("Depo Yönet", min_h=38, min_w=126)
        self.btn_wh_manage.clicked.connect(self._open_warehouse_manager)
        self.cb_item.setMinimumWidth(0)
        self.cb_wh.setMinimumWidth(0)
        self.cb_item.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cb_wh.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.sp_qty = NumberStepper(minimum=1, maximum=10_000_000, step=1)
        self.sp_qty.setValue(1)
        self.sp_qty.setMinimumHeight(42)

        self.ds_occurred_date = DateSelector(display_format="dd.MM.yyyy", placeholder="Tarih seç")
        self.ts_occurred_time = TimeSelector(display_format="HH:mm", placeholder="Saat seç")
        self.ds_occurred_date.setMinimumHeight(42)
        self.ts_occurred_time.setMinimumHeight(42)
        self.ts_occurred_time.setMinimumWidth(130)
        self.ts_occurred_time.setMaximumWidth(150)
        self._set_date_time_widgets(
            QDateTime.currentDateTime(),
            self.ds_occurred_date,
            self.ts_occurred_time,
        )

        self.cb_tx_reason = SwitchSelectWidget(
            multi=False,
            include_all=False,
            empty_text="Seçiniz",
            all_text="Seçiniz",
        )
        self.cb_tx_reason.currentIndexChanged.connect(self._sync_order_reference_state)

        self.le_order_ref = QLineEdit()
        self.le_order_ref.setMinimumHeight(42)
        self._order_ref_row = QWidget()
        order_ref_layout = QHBoxLayout(self._order_ref_row)
        order_ref_layout.setContentsMargins(0, 0, 0, 0)
        order_ref_layout.setSpacing(0)
        order_ref_layout.addWidget(self.le_order_ref)
        self.le_order_ref.setPlaceholderText("Sipariş no / referans (sipariş çıkışta zorunlu)")

        self.le_unit_cost = CurrencyAmountInput(decimals=3, currency="TRY", placeholder="Girişte zorunlu")
        self.le_unit_cost.setPlaceholderText("Girişte zorunlu")
        self.le_unit_cost.setMinimumHeight(50)

        self.cb_currency = SwitchSelectWidget(multi=False, all_text="Seçiniz")
        self.cb_currency.setPlaceholderText("Para birimi ara/seç")
        self.cb_currency.addItems(CURRENCY_OPTIONS)
        self.cb_currency.setCurrentText("TRY")
        self.cb_currency.currentIndexChanged.connect(self._sync_unit_cost_currency_badge)
        self.sw_unit_cost_tax_mode = SwitchButton()
        self.sw_unit_cost_tax_mode.setChecked(True)
        self.sw_unit_cost_tax_mode.toggled.connect(self._sync_unit_cost_tax_state)
        self.lbl_unit_cost_tax_gross = QLabel("KDV Dahil")
        self.lbl_unit_cost_tax_gross.setObjectName("SubTitle")
        self.lbl_unit_cost_tax_net = QLabel("KDV Hariç")
        self.lbl_unit_cost_tax_net.setObjectName("SubTitle")
        self._unit_cost_tax_switch_row = QWidget()
        unit_cost_tax_switch_layout = QHBoxLayout(self._unit_cost_tax_switch_row)
        unit_cost_tax_switch_layout.setContentsMargins(0, 0, 0, 0)
        unit_cost_tax_switch_layout.setSpacing(10)
        unit_cost_tax_switch_layout.addWidget(self.lbl_unit_cost_tax_net, 0)
        unit_cost_tax_switch_layout.addWidget(self.sw_unit_cost_tax_mode, 0)
        unit_cost_tax_switch_layout.addWidget(self.lbl_unit_cost_tax_gross, 0)
        unit_cost_tax_switch_layout.addStretch(1)
        self.lbl_unit_cost_tax_hint = QLabel("", objectName="SubTitle")
        self.lbl_unit_cost_tax_hint.setWordWrap(True)
        self._unit_cost_tax_wrap = QWidget()
        unit_cost_tax_layout = QVBoxLayout(self._unit_cost_tax_wrap)
        unit_cost_tax_layout.setContentsMargins(0, 0, 0, 0)
        unit_cost_tax_layout.setSpacing(6)
        unit_cost_tax_layout.addWidget(self._unit_cost_tax_switch_row)
        unit_cost_tax_layout.addWidget(self.lbl_unit_cost_tax_hint)
        self.le_note = QLineEdit(); self.le_note.setPlaceholderText("Not (ops.)")
        self.le_note.setMinimumHeight(42)
        self.cb_company = SwitchSelectWidget(multi=False, all_text="Seçiniz")
        self.cb_company.setPlaceholderText("Firma seç (ops.)")
        self.btn_company_manage = _inline_action_btn("Firma Yönet", min_h=38, min_w=126)
        self.cb_company.setMinimumWidth(0)
        self.cb_company.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_company_manage.clicked.connect(self._open_company_manager)
        company_row = QHBoxLayout()
        company_row.setContentsMargins(0, 0, 0, 0)
        company_row.setSpacing(8)
        company_row.addWidget(self.cb_company, 1)
        company_row.addWidget(self.btn_company_manage)
        self.tx_file_picker = FileBadgePicker(
            button_text="Dosya Seç",
            clear_text=STOCK_MANAGER_CLEAR_TEXT,
            dialog_title="Belge / Fotoğraf Seç",
            dialog_filter="Tüm Dosyalar (*.*)",
            allow_multiple=True,
            show_clear_button=True,
            open_on_click=True,
        )
        self.tx_file_picker.setMinimumHeight(46)

        item_row = QHBoxLayout()
        item_row.setContentsMargins(0, 0, 0, 0)
        item_row.setSpacing(8)
        item_row.addWidget(self.cb_item, 1)
        item_row.addWidget(self.btn_item_manage)
        form.addRow("Ürün", item_row)
        wh_row = QHBoxLayout()
        wh_row.setContentsMargins(0, 0, 0, 0)
        wh_row.setSpacing(8)
        wh_row.addWidget(self.cb_wh, 1)
        wh_row.addWidget(self.btn_wh_manage)
        form.addRow("Depo", wh_row)
        form.addRow("Miktar", self.sp_qty)
        occurred_row = QHBoxLayout()
        occurred_row.setSpacing(8)
        occurred_row.addWidget(self.ds_occurred_date, 1)
        occurred_row.addWidget(self.ts_occurred_time, 0)
        form.addRow("İşlem Tarih/Saat", occurred_row)
        form.addRow("Sebep", self.cb_tx_reason)
        form.addRow("Sipariş Ref", self._order_ref_row)
        self._order_ref_label = form.labelForField(self._order_ref_row)
        form.addRow("Para Birimi", self.cb_currency)
        form.addRow("Birim Maliyet", self.le_unit_cost)
        form.addRow("Maliyet KDV", self._unit_cost_tax_wrap)
        self._unit_cost_tax_label = form.labelForField(self._unit_cost_tax_wrap)
        form.addRow("Muhatap", company_row)
        form.addRow("Belge/Fotoğraf", self.tx_file_picker)
        form.addRow("Not", self.le_note)
        self._sync_unit_cost_currency_badge()
        self._sync_order_reference_state()
        self._sync_unit_cost_tax_state()

        form_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        left_layout.addWidget(form_host, 1)

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text="Formu Temizle",
            save_new_text="Stok Giriş Kaydet",
            save_edit_text="Stok Giriş Kaydet",
        )
        self._workspace.set_editor_action_delete_supported(False)
        self.btn_clear_form = self._workspace.editor_action_bar.clear_button
        self.btn_submit_tx = self._workspace.editor_action_bar.save_button
        self.btn_submit_tx.setMinimumWidth(200)
        self._workspace.editor_action_bar.clearRequested.connect(self._reset_form_fields)
        self._workspace.editor_action_bar.saveRequested.connect(self._submit_active_tx)
        self._tx_actions_wrap = self._editor_actions_wrap

        status = QFrame(); status.setObjectName("SoftCard")
        sl = QHBoxLayout(status); sl.setContentsMargins(16, 12, 16, 12)
        self.lbl_on_hand = QLabel("Stok: -"); self.lbl_on_hand.setObjectName("Title")
        sl.addWidget(self.lbl_on_hand); sl.addStretch(1)
        self._tx_status_card = status

        left_layout.addWidget(self._tx_status_card)

        self.lbl_edit_mode_notice = QLabel(
            "Düzenleme modunda Belge/Fotoğraf ve Maliyet KDV modu güncellenebilir.",
            objectName="SubTitle",
        )
        self.lbl_edit_mode_notice.setWordWrap(True)
        self.lbl_edit_mode_notice.hide()
        left_layout.addWidget(self.lbl_edit_mode_notice)

        bulk_content = QWidget(self.bulk_panel)
        bulk_layout = QVBoxLayout(bulk_content)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.setSpacing(8)
        bulk_layout.setContentsMargins(10, 8, 10, 8)
        bulk_layout.addWidget(QLabel(STOCK_MANAGER_BULK_TITLE, objectName="Section"))
        self.bulk_summary = QLabel("Seçili hareket: 0", objectName="SubTitle")
        self.bulk_summary.setWordWrap(True)
        bulk_hint = QLabel("SEÇ ile işaretlediğin hareketler üzerinde toplu işlem yapabilirsin.", objectName="SubTitle")
        bulk_hint.setWordWrap(True)
        self.btn_bulk_export = _btn("Toplu Excel Dışa Aktar", "Primary", 42)
        self.btn_bulk_clear = _btn(STOCK_MANAGER_BULK_CLEAR_TEXT, "Ghost", 42)
        self.btn_bulk_export.clicked.connect(self._export_selected_txs)
        self.btn_bulk_clear.clicked.connect(self._clear_bulk_selection)
        bulk_layout.addWidget(self.bulk_summary)
        bulk_layout.addWidget(bulk_hint)
        bulk_layout.addWidget(self.btn_bulk_export)
        bulk_layout.addWidget(self.btn_bulk_clear)
        bulk_layout.addStretch(1)
        self.bulk_panel.hide()

        filters_host = QWidget(self._workspace.filters_host)
        flt = QVBoxLayout(filters_host); flt.setContentsMargins(0, 0, 0, 0); flt.setSpacing(8)

        self.le_tx_search = QLineEdit()
        self.le_tx_search.setObjectName("Search")
        self.le_tx_search.setPlaceholderText("Ara: tarih / yön / miktar / maliyet / para / sebep / not")
        self.le_filter_tx_ids = QLineEdit()
        self.le_filter_tx_ids.setObjectName("Search")
        self.le_filter_tx_ids.setPlaceholderText("Hareket ID filtresi (örn: 12,34,89)")

        self.cb_dir = SwitchSelectWidget(title="Yön", all_text="Tümü", multi=False, include_all=True)
        self.cb_dir.addItem("Giriş", "IN")
        self.cb_dir.addItem("Çıkış", "OUT")

        self.cb_reason = SwitchSelectWidget(title="Sebep", all_text="Tümü", multi=False, include_all=True)
        for reason_value, reason_label in self._all_reason_options:
            self.cb_reason.addItem(reason_label, reason_value)

        self.ds_range = DateSelector(
            display_format="dd.MM.yyyy",
            range_enabled=True,
            placeholder="Tarih aralığı",
        )
        self.ts_range = TimeSelector(
            display_format="HH:mm",
            range_enabled=True,
            placeholder="Saat aralığı",
        )
        self.ts_range.setMinimumWidth(210)
        self.ts_range.setMaximumWidth(240)

        self.cb_filter_currency = SwitchSelectWidget(title="Para", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_item = SwitchSelectWidget(title="Ürün", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_warehouse = SwitchSelectWidget(title="Depo", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_counterparty = SwitchSelectWidget(title="Muhatap", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_cost = SwitchSelectWidget(title="Maliyet", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_cost.addItem("Maliyetli", "has")
        self.cb_filter_cost.addItem("Maliyetsiz", "none")
        self.cb_filter_attachment = SwitchSelectWidget(title="Belge", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_attachment.addItem("Var", "has")
        self.cb_filter_attachment.addItem("Yok", "none")
        self.cb_filter_note = SwitchSelectWidget(title="Not", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_note.addItem("Var", "has")
        self.cb_filter_note.addItem("Yok", "none")
        self.cb_dir.setMinimumWidth(150)
        self.cb_reason.setMinimumWidth(160)
        self.cb_filter_currency.setMinimumWidth(150)
        self.cb_filter_item.setMinimumWidth(150)
        self.cb_filter_warehouse.setMinimumWidth(150)
        self.cb_filter_counterparty.setMinimumWidth(150)
        self.cb_filter_cost.setMinimumWidth(150)
        self.cb_filter_attachment.setMinimumWidth(150)
        self.cb_filter_note.setMinimumWidth(150)

        self.btn_clear_filter = _btn("Filtreyi Sıfırla", "SoftDanger", 40)

        self.btn_clear_filter.clicked.connect(self._clear_filters)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(self.le_tx_search, 2)
        row1.addWidget(self.cb_dir, 1)
        row1.addWidget(self.cb_reason, 1)
        row1.addWidget(self.btn_clear_filter, 0)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("Tarih"))
        row2.addWidget(self.ds_range, 1)
        row2.addWidget(QLabel("Saat"))
        row2.addWidget(self.ts_range, 0)
        row2.addWidget(self.cb_filter_warehouse, 1)
        row2.addWidget(self.cb_filter_note, 1)

        row3 = QHBoxLayout()
        row3.setSpacing(8)
        row3.addWidget(self.le_filter_tx_ids, 1)
        row3.addWidget(self.cb_filter_item, 1)
        row3.addWidget(self.cb_filter_currency, 1)
        row3.addWidget(self.cb_filter_counterparty, 1)
        
        row4 = QHBoxLayout()
        row4.setSpacing(8)
        row4.addWidget(self.cb_filter_cost, 1)
        row4.addWidget(self.cb_filter_attachment, 1)
        row4.addStretch(1)

        flt.addLayout(row1)
        flt.addLayout(row2)
        flt.addLayout(row3)
        flt.addLayout(row4)
        self.lbl_forced_tx_filter = QLabel("", objectName="SubTitle")
        self.lbl_forced_tx_filter.setWordWrap(True)
        self.lbl_forced_tx_filter.hide()
        flt.addWidget(self.lbl_forced_tx_filter)

        self.txs_list = StockTxListWidget()
        self.txs_list.tx_selected.connect(self._on_tx_row_selected)
        self.txs_list.source_button_clicked.connect(self._on_tx_source_button_clicked)
        self.txs_list.order_button_clicked.connect(self._on_tx_order_button_clicked)
        self.txs_list.listing_button_clicked.connect(self._on_tx_listing_button_clicked)
        self.txs_list.image_clicked.connect(self._on_tx_image_clicked)
        self.txs_list.bulk_selection_changed.connect(self._on_tx_bulk_selection_changed)
        self._workspace.set_editor_widget(editor_host)
        self._workspace.set_bulk_widget(bulk_content)
        self._workspace.set_filters_widget(filters_host)
        self._workspace.set_list_widget(self.txs_list)
        self._workspace.footer_bar.setObjectName("BottomBar")
        self._workspace.footer_bar.page_size_label.setText("Sayfa başına")

        splitter.setChildrenCollapsible(True)
        splitter.setSizes([0, 1660])
        splitter.setHandleWidth(6)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        self._workspace_adapter = StockTxWorkspaceBehaviorAdapter(self)
        self._workspace_behavior = self._workspace.create_behavior_controller(
            adapter=self._workspace_adapter,
        )

        self.cb_item.currentIndexChanged.connect(self.refresh_balance)
        self.cb_item.currentIndexChanged.connect(self._sync_unit_cost_tax_state)
        self.cb_wh.currentIndexChanged.connect(self.refresh_balance)
        self.le_tx_search.textChanged.connect(self._schedule_txs_refresh)
        self.le_filter_tx_ids.textChanged.connect(self._schedule_txs_refresh)
        self.cb_dir.currentIndexChanged.connect(self._schedule_txs_refresh)
        self.cb_reason.currentIndexChanged.connect(self._schedule_txs_refresh)
        self.cb_filter_item.currentIndexChanged.connect(self._schedule_txs_refresh)
        self.cb_filter_warehouse.currentIndexChanged.connect(self._schedule_txs_refresh)
        self.cb_filter_currency.currentIndexChanged.connect(self._schedule_txs_refresh)
        self.cb_filter_counterparty.currentIndexChanged.connect(self._schedule_txs_refresh)
        self.cb_filter_cost.currentIndexChanged.connect(self._schedule_txs_refresh)
        self.cb_filter_attachment.currentIndexChanged.connect(self._schedule_txs_refresh)
        self.cb_filter_note.currentIndexChanged.connect(self._schedule_txs_refresh)
        self.ds_range.rangeChanged.connect(self._schedule_txs_refresh)
        self.ts_range.rangeChanged.connect(self._schedule_txs_refresh)

        self._set_filter_range_widgets(
            QDateTime.currentDateTime().addDays(-30),
            QDateTime.currentDateTime(),
        )
        self._set_tx_mode(self.MODE_IN, emit_refresh=False, force_default_reason=True)
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
        # Delay first heavy load so the dialog paints before DB queries.
        QTimer.singleShot(0, self.refresh_all)

    def _schedule_txs_refresh(self, *_args, immediate: bool = False) -> None:
        if self._tx_refresh_suppressed:
            return
        timer = self._tx_refresh_timer
        if immediate:
            if timer.isActive():
                timer.stop()
            self.refresh_txs_list()
            return
        timer.start()

    def _invalidate_tx_query_cache(self) -> None:
        self._tx_query_cache_key = None
        self._tx_query_cache_records = []

    def _queue_stock_domain_refresh(self) -> None:
        if self._signal_refresh_queued:
            return
        self._signal_refresh_queued = True
        QTimer.singleShot(0, self._apply_stock_domain_refresh)

    def _on_tx_created_signal(self, tx_id: int) -> None:
        created_tx_id = self._safe_tx_id(tx_id)
        if created_tx_id is not None:
            self._pending_signal_tx_id = created_tx_id
        self._ensure_tx_filters_include_datetime(QDateTime.currentDateTime())
        self._invalidate_tx_query_cache()
        self._queue_stock_domain_refresh()

    def _on_stock_domain_refreshed(self) -> None:
        self._invalidate_tx_query_cache()
        self._queue_stock_domain_refresh()

    def _apply_stock_domain_refresh(self) -> None:
        self._signal_refresh_queued = False
        self.refresh_balance_and_txs()
        pending_tx_id = self._pending_signal_tx_id
        if pending_tx_id is not None:
            self.txs_list.set_selected_id(pending_tx_id)
            self._pending_signal_tx_id = None

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _sync_unit_cost_currency_badge(self, *_args) -> None:
        currency = str(self.cb_currency.currentText() or "").strip().upper() or "TRY"
        self.le_unit_cost.setCurrency(currency)

    def _selected_item_vat_rate(self) -> Optional[float]:
        item_id = self.cb_item.currentData()
        try:
            item_key = int(item_id)
        except Exception:
            return None
        vat_rate = self._item_vat_rate_by_id.get(item_key)
        try:
            return float(vat_rate) if vat_rate not in (None, "") else None
        except Exception:
            return None

    def _get_unit_cost_tax_mode(self) -> str:
        return "gross" if bool(self.sw_unit_cost_tax_mode.isChecked()) else "net"

    def _set_unit_cost_tax_mode(self, mode: Any) -> None:
        normalized = str(mode or "").strip().casefold()
        self.sw_unit_cost_tax_mode.setChecked(normalized == "gross")

    def _sync_selected_tx_unit_cost_display(self) -> None:
        if not self._is_tx_attachment_update_mode():
            return
        tx = self.txs_list.selected_tx()
        if tx is None:
            self.le_unit_cost.setText("")
            return

        display_value = _unit_cost_value_for_display(
            getattr(tx, "unit_cost", None),
            input_mode=self._get_unit_cost_tax_mode(),
            vat_rate=getattr(tx, "unit_cost_vat_rate", None),
        )
        if display_value is None:
            self.le_unit_cost.setText("")
            return

        try:
            self.le_unit_cost.setValue(float(display_value))
        except Exception:
            self.le_unit_cost.setText(_fmt_num(display_value, default=""))

    def _sync_unit_cost_tax_state(self, *_args) -> None:
        wrap = self._unit_cost_tax_wrap
        label = self._unit_cost_tax_label
        hint = self.lbl_unit_cost_tax_hint
        gross_label = self.lbl_unit_cost_tax_gross
        net_label = self.lbl_unit_cost_tax_net

        visible = self._tx_mode == self.MODE_IN or self._is_tx_attachment_update_mode()
        wrap.setVisible(visible)
        label.setVisible(visible)
        if not visible:
            return

        vat_rate = self._selected_item_vat_rate()
        mode = self._get_unit_cost_tax_mode()
        gross_active = mode == "gross"
        net_active = mode == "net"
        gross_label.setStyleSheet(
            "color: #15803d; font-weight: 800;" if gross_active else "color: #64748b; font-weight: 600;"
        )
        net_label.setStyleSheet(
            "color: #b45309; font-weight: 800;" if net_active else "color: #64748b; font-weight: 600;"
        )
        if mode == "net":
            if vat_rate is None:
                hint.setText("KDV hariç seçiminde stok kartında KDV oranı zorunlu.")
            else:
                hint.setText(f"Girilen tutar stok kartındaki %{vat_rate:g} KDV ile brüte çevrilir.")
        else:
            if vat_rate is None:
                hint.setText("Girilen maliyet KDV dahil kabul edilir.")
            else:
                hint.setText(f"Girilen maliyet KDV dahil kabul edilir. Stok kartı KDV oranı: %{vat_rate:g}.")

        self._sync_selected_tx_unit_cost_display()

    def _is_order_out_reason_selected(self) -> bool:
        reason = str(self.cb_tx_reason.currentData() or "").strip()
        return reason == str(StockTxReason.order_out.value)

    def _sync_order_reference_state(self, *_args) -> None:
        need_order_ref = self._tx_mode == self.MODE_OUT and self._is_order_out_reason_selected()
        lock_fields = self._is_tx_attachment_update_mode()
        self._order_ref_row.setVisible(need_order_ref)
        self._order_ref_label.setVisible(need_order_ref)
        self.le_order_ref.setEnabled(need_order_ref and not lock_fields)
        if need_order_ref:
            self.le_order_ref.setPlaceholderText("Sipariş no / referans (zorunlu)")
        else:
            self.le_order_ref.setPlaceholderText("Sipariş çıkışta zorunlu")
            self.le_order_ref.clear()

    def _apply_mode_tab_style(self) -> None:
        active_in = self._tx_mode == self.MODE_IN
        self.btn_tab_in.setProperty("active", active_in)
        self.btn_tab_out.setProperty("active", not active_in)
        self._repolish(self.btn_tab_in)
        self._repolish(self.btn_tab_out)

    def _is_tx_mode_locked(self, mode: str) -> bool:
        normalized = self.MODE_OUT if str(mode or "").upper().endswith("OUT") else self.MODE_IN
        btn = self.btn_tab_out if normalized == self.MODE_OUT else self.btn_tab_in
        return bool(btn.property("locked"))

    def _request_tx_mode(self, mode: str) -> None:
        normalized = self.MODE_OUT if str(mode or "").upper().endswith("OUT") else self.MODE_IN
        if self._is_tx_mode_locked(normalized):
            return
        self._set_tx_mode(normalized)

    def _sync_tx_mode_switch_state(self) -> None:
        locked_mode: Optional[str] = None
        panel_open = self._is_editor_panel_open()
        if self._left_mode == "edit" and panel_open:
            selected = self.txs_list.selected_tx()
            if selected is not None:
                direction = str(getattr(selected, "direction", "") or "").upper()
                locked_mode = self.MODE_OUT if direction.endswith("OUT") else self.MODE_IN

        lock_in = False
        lock_out = False
        if self._is_tx_attachment_update_mode():
            lock_in = True
            lock_out = True
        elif locked_mode == self.MODE_IN:
            lock_out = True
        elif locked_mode == self.MODE_OUT:
            lock_in = True

        for btn, locked in ((self.btn_tab_in, lock_in), (self.btn_tab_out, lock_out)):
            btn.setEnabled(True)
            btn.setProperty("locked", locked)
            btn.setCursor(
                Qt.CursorShape.PointingHandCursor
                if not locked
                else Qt.CursorShape.ArrowCursor
            )
            self._repolish(btn)
        self._sync_tx_form_interaction_state()

    def _is_tx_attachment_update_mode(self) -> bool:
        if str(self._left_mode or "").lower() != "edit":
            return False
        if not self._is_editor_panel_open():
            return False
        return self.txs_list.selected_tx() is not None

    def _sync_tx_form_interaction_state(self) -> None:
        attachment_update_mode = self._is_tx_attachment_update_mode()

        locked_widgets = (
            self.cb_item,
            self.btn_item_manage,
            self.cb_wh,
            self.btn_wh_manage,
            self.sp_qty,
            self.ds_occurred_date,
            self.ts_occurred_time,
            self.cb_tx_reason,
            self.le_order_ref,
            self.le_unit_cost,
            self.cb_currency,
            self.cb_company,
            self.le_note,
        )
        for widget in locked_widgets:
            widget.setEnabled(not attachment_update_mode)

        self.tx_file_picker.setEnabled(True)
        self.sw_unit_cost_tax_mode.setEnabled(True)
        self.btn_clear_form.setVisible(not attachment_update_mode)
        self.lbl_edit_mode_notice.setVisible(attachment_update_mode)

        if attachment_update_mode:
            self.lbl_mode_hint.setText("Düzenle: belge/fotoğraf ve maliyet KDV modu güncellenebilir.")
            self.btn_submit_tx.setText("Belge/Fotoğraf + KDV Modu Güncelle")
            self.btn_submit_tx.setObjectName("Primary")
            self._repolish(self.btn_submit_tx)
            self._sync_order_reference_state()
            self._sync_unit_cost_tax_state()
            return

        if self._tx_mode == self.MODE_IN:
            self.lbl_mode_hint.setText("Stok Giriş: birim maliyet zorunlu.")
            self.btn_submit_tx.setText("Stok Giriş Kaydet")
            self.btn_submit_tx.setObjectName("Success")
        else:
            self.lbl_mode_hint.setText("Stok Çıkış: birim maliyet opsiyonel.")
            self.btn_submit_tx.setText("Stok Çıkış Kaydet")
            self.btn_submit_tx.setObjectName("DangerStrong")
        self._repolish(self.btn_submit_tx)
        self._sync_order_reference_state()
        self._sync_unit_cost_tax_state()

    def _set_tx_mode(self, mode: str, *, emit_refresh: bool = True, force_default_reason: bool = False):
        normalized = self.MODE_OUT if str(mode or "").upper().endswith("OUT") else self.MODE_IN
        self._tx_mode = normalized
        self._apply_mode_tab_style()
        self._refresh_form_reason_choices(force_default=force_default_reason)

        if self._tx_mode == self.MODE_IN:
            self.lbl_mode_hint.setText("Stok Giriş: birim maliyet zorunlu.")
            self.le_unit_cost.setPlaceholderText("Girişte zorunlu")
            self.btn_submit_tx.setText("Stok Giriş Kaydet")
            self.btn_submit_tx.setObjectName("Success")
        else:
            self.lbl_mode_hint.setText("Stok Çıkış: birim maliyet opsiyonel.")
            self.le_unit_cost.setPlaceholderText("Çıkışta opsiyonel")
            self.btn_submit_tx.setText("Stok Çıkış Kaydet")
            self.btn_submit_tx.setObjectName("DangerStrong")
        self._repolish(self.btn_submit_tx)
        self._sync_tx_mode_switch_state()
        self._sync_unit_cost_tax_state()
        self._sync_out_unit_cost_suggestion(force=True)

        if emit_refresh:
            self.refresh_balance_and_txs()

    def _refresh_form_reason_choices(self, *, force_default: bool = False):
        current_reason = self.cb_tx_reason.currentData()
        options = self._form_reason_options.get(self._tx_mode, [])
        with QSignalBlocker(self.cb_tx_reason):
            self.cb_tx_reason.clear()
            for value, label in options:
                self.cb_tx_reason.addItem(label, value)
            restored = False
            if current_reason is not None and not force_default:
                idx = self.cb_tx_reason.findData(current_reason)
                if idx >= 0:
                    self.cb_tx_reason.setCurrentIndex(idx)
                    restored = True
            if not restored:
                default_reason = StockTxReason.manual_in.value if self._tx_mode == self.MODE_IN else StockTxReason.manual_out.value
                idx = self.cb_tx_reason.findData(default_reason)
                self.cb_tx_reason.setCurrentIndex(idx if idx >= 0 else 0)
        self._sync_order_reference_state()

    def _submit_active_tx(self):
        if self._is_tx_attachment_update_mode():
            self._update_selected_tx_edit_fields()
            return
        if self._tx_mode == self.MODE_OUT:
            self.on_out()
            return
        self.on_in()

    def _reset_form_fields(self):
        self.sp_qty.setValue(1)
        self._set_date_time_widgets(
            QDateTime.currentDateTime(),
            self.ds_occurred_date,
            self.ts_occurred_time,
        )
        self._refresh_form_reason_choices(force_default=True)
        self.le_order_ref.clear()
        self.le_unit_cost.setText("")
        self.cb_currency.setCurrentText("TRY")
        self._set_unit_cost_tax_mode("gross")
        self.le_note.clear()
        self.cb_company.setCurrentIndex(-1)
        self.tx_file_picker.clearFiles()
        self._sync_order_reference_state()
        self._sync_unit_cost_tax_state()
        self._sync_out_unit_cost_suggestion(force=True)

    @staticmethod
    def _as_positive_float(value: Any) -> Optional[float]:
        try:
            parsed = float(value)
        except Exception:
            return None
        if parsed <= 0:
            return None
        return parsed

    def _resolve_out_cost_suggestion(self) -> tuple[Optional[float], str]:
        item_id = self.cb_item.currentData()
        wh_id = self.cb_wh.currentData()
        default_currency = str(self.cb_currency.currentText() or "TRY").strip().upper() or "TRY"
        if item_id in (None, "") or wh_id in (None, ""):
            return None, default_currency

        try:
            item_key = int(item_id)
            wh_key = int(wh_id)
        except Exception:
            return None, default_currency

        res = action_list_item_balances(warehouse_id=wh_key, only_active=False)
        if not res.success:
            return None, default_currency

        for row in (res.data.get("records", []) or []):
            item_obj = row.get("item")
            row_item_id = _stock_row_pk(item_obj) or 0
            if row_item_id != item_key:
                continue

            avg_cost = self._as_positive_float(row.get("avg_unit_cost"))
            avg_currency = str(row.get("avg_cost_currency") or default_currency).strip().upper() or default_currency
            return avg_cost, avg_currency

        return None, default_currency

    def _sync_out_unit_cost_suggestion(self, *, force: bool = False) -> None:
        self._out_avg_cost_suggestion = None
        self._out_avg_currency_suggestion = str(self.cb_currency.currentText() or "TRY").strip().upper() or "TRY"

        if self._tx_mode != self.MODE_OUT:
            return
        if self._is_tx_attachment_update_mode():
            return

        suggested_cost, suggested_currency = self._resolve_out_cost_suggestion()
        self._out_avg_cost_suggestion = suggested_cost
        self._out_avg_currency_suggestion = suggested_currency

        if suggested_cost is None:
            self.le_unit_cost.setPlaceholderText("Çıkışta opsiyonel")
            return

        self.le_unit_cost.setPlaceholderText(
            f"Hareketli ortalama: {_fmt_num(suggested_cost)} {suggested_currency}"
        )

        if force or (not self.le_unit_cost.has_value()):
            try:
                self.le_unit_cost.setValue(float(suggested_cost))
            except Exception:
                self.le_unit_cost.setText(_fmt_num(suggested_cost))
            if suggested_currency:
                if self.cb_currency.findText(suggested_currency) < 0:
                    self.cb_currency.addItem(suggested_currency, suggested_currency)
                self.cb_currency.setCurrentText(suggested_currency)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.txs_list.sync_dynamic_row_width()
        self._sync_guidance_overlays_geometry()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()
        self._sync_card_spin_state()

    def _refresh_left_panel_header(self):
        mode = str(self._left_mode or "edit").lower()
        if mode == "new":
            self.left_panel_title.setText("Yeni İşlem")
            self.left_panel_hint.setText("Yeni stok hareketi oluşturmak için formu doldur.")
            return
        if mode == "bulk":
            self.left_panel_title.setText(STOCK_MANAGER_LEFT_BULK_TITLE)
            self.left_panel_hint.setText("SEÇ ile işaretlenen hareketler için toplu işlem yapabilirsin.")
            return
        self.left_panel_title.setText("İşlem Düzenle")
        selected = self.txs_list.selected_tx()
        if selected is None:
            self.left_panel_hint.setText("Düzenlemek için sağdaki listeden bir hareket seç.")
            return
        tx_id = _stock_row_pk(selected)
        self.left_panel_hint.setText(f"Seçili hareket: #{tx_id if tx_id is not None else '-'}")

    def _set_left_mode(self, mode: str):
        mode_key = str(mode or "").lower()
        if mode_key not in {"new", "edit", "bulk"}:
            mode_key = "edit"
        self._left_mode = mode_key
        self._workspace.set_editor_action_mode(mode_key)

        show_editor = self._left_mode in {"new", "edit"}
        self._tx_tabs_frame.setVisible(show_editor)
        self.lbl_mode_hint.setVisible(show_editor)
        self._tx_form_scroll.setVisible(show_editor)
        self._tx_actions_wrap.setVisible(show_editor)
        self._tx_status_card.setVisible(show_editor)
        self.bulk_panel.setVisible(not show_editor)
        self._update_bulk_panel_state()

        self._refresh_left_panel_header()
        self._sync_sidebar_state_from_splitter()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()
        self._sync_tx_mode_switch_state()
        self._sync_card_spin_state()

    def _update_bulk_panel_state(self):
        count = self.txs_list.bulk_selected_count()
        self.bulk_summary.setText(f"Seçili hareket: {count}")
        self.btn_bulk_export.setEnabled(count > 0)

    def _prepare_new_tx_workspace(self):
        self.txs_list.clear_active_selection()
        self._reset_form_fields()
        self._set_left_mode("new")

    def _clear_tx_workspace_state(self):
        self._clear_active_edit_selection()

    def _sync_tx_workspace_state(self):
        self._update_bulk_panel_state()
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()
        self._sync_tx_mode_switch_state()
        self._sync_card_spin_state()

    def _on_tx_bulk_selection_changed(self, _count: int):
        self._update_bulk_panel_state()
        if self._left_mode == "bulk" and self._is_editor_panel_open() and self.txs_list.bulk_selected_count() <= 0:
            self._close_editor_panel()
            return
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def _clear_bulk_selection(self):
        self.txs_list.clear_bulk_selection()
        self._update_bulk_panel_state()
        if self._left_mode == "bulk" and self._is_editor_panel_open():
            self._close_editor_panel()
        else:
            self._sync_sidebar_state_from_splitter()

    def _export_selected_txs(self):
        selected_txs = self.txs_list.bulk_selected_txs()
        if not selected_txs:
            self.error("Hata", "Toplu dışa aktarım için en az bir hareket seçmelisin.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Toplu Excel kaydet", "", "Excel (*.xlsx)")
        if not path:
            return
        res = action_export_txs_excel(txs=selected_txs, output_path=path)
        if res.success:
            self.info("OK", res.message or "Toplu Excel kaydedildi.")
        else:
            self.error("Hata", f"{res.message}\n{res.data}")

    def _sync_guidance_overlays_geometry(self):
        self._workspace.sync_list_loading_geometry()
        self._workspace_shell.sync_guidance_geometry()

    def _sync_focus_guidance_state(self):
        panel_open = self._is_editor_panel_open()
        selected = self.txs_list.selected_tx()
        bulk_count = self.txs_list.bulk_selected_count()
        bulk_mode = self._left_mode == "bulk" and panel_open
        self.txs_list.set_select_button_guide_enabled(bulk_mode and bulk_count <= 0)
        self.txs_list.set_active_spin_allowed(self._left_mode == "edit" and panel_open and selected is not None)

    def _update_edit_lock_state(self):
        return

    def _sync_card_spin_state(self):
        panel_open = self._is_editor_panel_open()
        selected = self.txs_list.selected_tx()
        allow_spin = self._left_mode == "edit" and panel_open and selected is not None
        self.txs_list.set_active_spin_allowed(bool(allow_spin))

    def _is_editor_panel_open(self) -> bool:
        return self._workspace_shell.is_left_panel_open()

    def _sync_sidebar_state_from_splitter(self):
        self._workspace.sync_list_loading_geometry()
        self._workspace_shell.sync_guidance_geometry()
        self._workspace_behavior.sync_state()
        self.txs_list.sync_dynamic_row_width()

    def _set_list_loading(self, busy: bool, message: str = "Stok hareketleri yükleniyor...") -> None:
        self._workspace.set_list_loading(bool(busy), message=message)

    def _open_editor_panel(self):
        self._workspace_shell.open_left_panel(min_left=360, min_right=280)
        self._sync_sidebar_state_from_splitter()

    def _clear_active_edit_selection(self):
        self.txs_list.clear_active_selection()
        self._reset_form_fields()
        self._sync_tx_mode_switch_state()

    def _close_editor_panel(self):
        if self._left_mode == "edit":
            self._clear_active_edit_selection()
        self._workspace_shell.close_left_panel()
        self._sync_sidebar_state_from_splitter()

    def _open_new_form(self):
        self.txs_list.clear_active_selection()
        self._reset_form_fields()
        self._set_left_mode("new")
        self._open_editor_panel()

    @staticmethod
    def _as_qdatetime(value: Any) -> QDateTime:
        if isinstance(value, QDateTime):
            return value if value.isValid() else QDateTime()
        if isinstance(value, datetime):
            return QDateTime(
                QDate(value.year, value.month, value.day),
                QTime(value.hour, value.minute, value.second),
            )
        text = str(value or "").strip()
        if not text:
            return QDateTime()
        for fmt in (
            Qt.DateFormat.ISODateWithMs,
            Qt.DateFormat.ISODate,
        ):
            qdt = QDateTime.fromString(text, fmt)
            if qdt.isValid():
                return qdt
        for fmt in (
            "yyyy-MM-dd HH:mm:ss",
            "yyyy-MM-ddTHH:mm:ss",
            "yyyy-MM-dd HH:mm:ss.zzz",
            "yyyy-MM-ddTHH:mm:ss.zzz",
            "dd.MM.yyyy HH:mm:ss",
            "dd.MM.yyyy HH:mm",
        ):
            qdt = QDateTime.fromString(text, fmt)
            if qdt.isValid():
                return qdt
        return QDateTime()

    @staticmethod
    def _set_switch_data(widget: SwitchSelectWidget, data: Any):
        idx = widget.findData(data)
        if idx >= 0:
            widget.setCurrentIndex(idx)
            return
        txt = str(data or "").strip()
        if not txt:
            return
        idx = widget.findText(txt)
        if idx >= 0:
            widget.setCurrentIndex(idx)

    @staticmethod
    def _trace_datetime_text(value: Any) -> str:
        qdt = StockTxDialog._as_qdatetime(value)
        if qdt.isValid():
            return qdt.toString("dd.MM.yyyy HH:mm")
        text = str(value or "").strip()
        return text or "-"

    def _on_tx_source_button_clicked(self, tx) -> None:
        if tx is None:
            return
        try:
            item_id = int(getattr(tx, "item_id", 0) or 0)
        except Exception:
            item_id = 0
        if item_id <= 0:
            self.error("Hata", "Bu harekete bağlı stok kartı bulunamadı.")
            return
        item_name = self._item_name_from_id(item_id)
        from .stock_item_manager_dialog import StockItemManagerDialog
        item_dialog = StockItemManagerDialog(self)
        if item_name and item_name != "-":
            item_dialog.setWindowTitle(f"Stok Kartları • {item_name}")
        item_dialog.apply_forced_item_filter(item_id=item_id)
        item_dialog.open_full()

    def _apply_listing_filter_to_window(self, listing_window: QWidget, listing_id: str) -> None:
        listing_ref = str(listing_id or "").strip()
        if not listing_ref:
            return

        try:
            with QSignalBlocker(listing_window.search_input), QSignalBlocker(listing_window.status_filter):
                listing_window.search_input.setText(listing_ref)
                listing_window.status_filter.setSelectedTexts([])
        except Exception:
            pass

        try:
            listing_window.apply_db_filters()
        except Exception:
            pass

    def _on_tx_listing_button_clicked(self, tx) -> None:
        if tx is None:
            return

        listing_id = _extract_listing_id_from_tx(tx)
        if not listing_id:
            self.error("Hata", "Bu harekette ilan referansi bulunamadi.")
            return

        try:
            from Listing.views.listing_manager_window import ListingManagerWindow  # pylint: disable=import-outside-toplevel
        except Exception as e:
            self.error("Hata", f"Ilanlar penceresi acilamadi.\n{e}")
            return

        listing_window = self._listing_from_tx_window
        if listing_window is None:
            listing_window = ListingManagerWindow(parent=self)
            try:
                listing_window.setWindowFlag(Qt.WindowType.Window, True)
            except Exception:
                pass
            self._listing_from_tx_window = listing_window

        self._apply_listing_filter_to_window(listing_window, listing_id)
        listing_window.showMaximized()
        listing_window.raise_()
        listing_window.activateWindow()

        # If initial async load is still running, retry once.
        QTimer.singleShot(
            450,
            lambda lw=listing_window, lid=listing_id: self._apply_listing_filter_to_window(lw, lid),
        )

    def _apply_order_filter_to_orders_window(self, orders_window: QWidget, order_number: str) -> None:
        order_no = str(order_number or "").strip()
        if not order_no:
            return
        if orders_window is None:
            return

        try:
            ensure_res = orders_window.ensure_order_numbers_loaded([order_no])
        except Exception:
            ensure_res = None
        if ensure_res is not None and getattr(ensure_res, "success", True) is False:
            self.error("Hata", f"{getattr(ensure_res, 'message', 'Sipariş yüklenemedi.')}\n{getattr(ensure_res, 'data', None)}")
            return

        try:
            blockers = [
                QSignalBlocker(orders_window.global_search),
                QSignalBlocker(orders_window.search_input),
                QSignalBlocker(orders_window.customer_input),
                QSignalBlocker(orders_window.tracking_input),
                QSignalBlocker(orders_window.amount_min_input),
                QSignalBlocker(orders_window.amount_max_input),
                QSignalBlocker(orders_window.cargo_filter),
                QSignalBlocker(orders_window.processed_filter),
                QSignalBlocker(orders_window.order_status_filter),
            ]
            orders_window.date_range.setSignalsBlocked(True)
            try:
                orders_window.global_search.setText(order_no)
                if order_no.isdigit():
                    orders_window.search_input.setText(order_no)
                else:
                    orders_window.search_input.clear()

                orders_window.customer_input.clear()
                orders_window.tracking_input.clear()
                orders_window.amount_min_input.clear()
                orders_window.amount_max_input.clear()

                self._set_switch_data(orders_window.cargo_filter, "all")
                self._set_switch_data(orders_window.processed_filter, "all")
                self._set_switch_data(orders_window.order_status_filter, "all")

                today = QDate.currentDate()
                orders_window.date_range.setRange(today.addYears(-5), today.addDays(1))
            finally:
                orders_window.date_range.setSignalsBlocked(False)
                del blockers
        finally:
            orders_window.date_range.setSignalsBlocked(False)

        try:
            orders_window.apply_filters()
        except Exception:
            pass

    def _on_tx_order_button_clicked(self, tx) -> None:
        if tx is None:
            return

        order_number = _extract_order_number_from_tx(tx)
        if not order_number:
            self.error("Hata", "Bu harekette sipariş referansı bulunamadı.")
            return

        try:
            from Orders.views.views import OrdersManagerWindow  # pylint: disable=import-outside-toplevel
        except Exception as e:
            self.error("Hata", f"Siparişler penceresi açılamadı.\n{e}")
            return

        orders_window = self._orders_from_tx_window
        if orders_window is None:
            orders_window = OrdersManagerWindow(parent=self)
            try:
                orders_window.setWindowFlag(Qt.WindowType.Window, True)
            except Exception:
                pass
            self._orders_from_tx_window = orders_window

        try:
            orders_window.list_widget.reload_orders()
        except Exception:
            pass

        self._apply_order_filter_to_orders_window(orders_window, order_number)
        orders_window.showMaximized()
        orders_window.raise_()
        orders_window.activateWindow()

        # Pencere ilk kez açıldığında liste asenkron yükleniyorsa filtreyi yeniden uygula.
        QTimer.singleShot(450, lambda ow=orders_window, ono=order_number: self._apply_order_filter_to_orders_window(ow, ono))

    def _on_tx_image_clicked(self, tx) -> None:
        if tx is None:
            return
        try:
            item_id = int(getattr(tx, "item_id", 0) or 0)
        except Exception:
            item_id = 0
        if item_id <= 0:
            return
        path = _first_image_path(self._item_image_by_id.get(item_id, ""))
        if self._tx_image_preview is None:
            self._tx_image_preview = ImagePreviewDialog(self)
        preview = self._tx_image_preview
        preview.set_image_path(path or None)
        preview.show()
        preview.raise_()
        preview.activateWindow()

    def _on_tx_row_selected(self, tx):
        if tx is None:
            if self._left_mode == "edit":
                self._reset_form_fields()
            self._refresh_left_panel_header()
            self._sync_focus_guidance_state()
            self._update_edit_lock_state()
            self._sync_tx_mode_switch_state()
            self._sync_card_spin_state()
            if self._left_mode == "edit" and self._is_editor_panel_open():
                self._sync_sidebar_state_from_splitter()
            return
        if self._left_mode != "edit":
            self._refresh_left_panel_header()
            self._sync_tx_mode_switch_state()
            self._sync_card_spin_state()
            return
        direction = str(getattr(tx, "direction", "") or "")
        self._set_tx_mode(self.MODE_OUT if direction.endswith("OUT") else self.MODE_IN, emit_refresh=False)

        self._set_switch_data(self.cb_item, getattr(tx, "item_id", None))
        self._set_switch_data(self.cb_wh, getattr(tx, "warehouse_id", None))

        try:
            qty_val = float(getattr(tx, "qty", 1) or 1)
            self.sp_qty.setValue(max(1, int(round(qty_val))))
        except Exception:
            self.sp_qty.setValue(1)

        occurred_at = self._as_qdatetime(getattr(tx, "occurred_at", None))
        if occurred_at.isValid():
            self._set_date_time_widgets(
                occurred_at,
                self.ds_occurred_date,
                self.ts_occurred_time,
            )

        self._set_switch_data(self.cb_tx_reason, getattr(tx, "reason", None))
        if self._is_order_out_reason_selected():
            self.le_order_ref.setText(str(_extract_order_number_from_tx(tx) or "").strip())
        else:
            self.le_order_ref.clear()
        self._sync_order_reference_state()

        currency = str(getattr(tx, "currency", "") or "").strip()
        if currency:
            if self.cb_currency.findText(currency) < 0:
                self.cb_currency.addItem(currency, currency)
            self.cb_currency.setCurrentText(currency)

        stored_input_mode = str(getattr(tx, "unit_cost_input_mode", "") or "").strip().casefold()
        if stored_input_mode in {"gross", "net"}:
            self._set_unit_cost_tax_mode(stored_input_mode)
        else:
            self._set_unit_cost_tax_mode("gross")
        self._sync_unit_cost_tax_state()

        counterparty = str(getattr(tx, "counterparty", "") or "").strip()
        if counterparty:
            if self.cb_company.findText(counterparty) < 0:
                self.cb_company.addItem(counterparty, counterparty)
            self.cb_company.setCurrentText(counterparty)
        else:
            self.cb_company.setCurrentIndex(-1)

        self.le_note.setText(str(getattr(tx, "note", "") or "").strip())

        tx_files: list[str] = []
        raw_attachments = getattr(tx, "attachments", None)
        if isinstance(raw_attachments, list):
            tx_files = [str(p or "").strip() for p in raw_attachments if str(p or "").strip()]
        elif raw_attachments:
            raw_text = str(raw_attachments or "").strip()
            if raw_text:
                try:
                    parsed = json.loads(raw_text)
                    if isinstance(parsed, list):
                        tx_files = [str(p or "").strip() for p in parsed if str(p or "").strip()]
                    elif isinstance(parsed, str) and parsed.strip():
                        tx_files = [parsed.strip()]
                except Exception:
                    tx_files = [raw_text]
        self.tx_file_picker.setFiles(tx_files, emit_signal=False)
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()
        self._sync_tx_mode_switch_state()
        self._sync_card_spin_state()

    def _refresh_company_choices(self):
        current = self.cb_company.currentText()
        res = action_list_companies()
        with QSignalBlocker(self.cb_company):
            self.cb_company.clear()
            if res.success:
                for c in (res.data.get("records", []) or []):
                    self.cb_company.addItem(getattr(c, "name", "") or "")
        if current:
            idx = self.cb_company.findText(current)
            if idx >= 0:
                self.cb_company.setCurrentIndex(idx)

    def _open_company_manager(self):
        try:

            from .company_manager_dialog import CompanyManagerDialog
            CompanyManagerDialog(self).open_full()
            self._refresh_company_choices()
        except Exception as e:
            self.error("Hata", f"Firma yönetimi açılamadı.\n{e}")

    def _open_warehouse_manager(self):
        try:
            from .warehouse_manager_dialog import WarehouseManagerDialog
            WarehouseManagerDialog(self).open_full()
            self.refresh_all()
        except Exception as e:
            self.error("Hata", f"Depo yönetimi açılamadı.\n{e}")

    def _open_item_manager(self):
        try:
            from .stock_item_manager_dialog import StockItemManagerDialog
            StockItemManagerDialog(self).open_full()
            self.refresh_all()
        except Exception as e:
            self.error("Hata", f"Stok kartları açılamadı.\n{e}")

    @staticmethod
    def _set_date_time_widgets(
        date_time: QDateTime,
        date_widget: DateSelector,
        time_widget: TimeSelector,
    ) -> None:
        dt = date_time if isinstance(date_time, QDateTime) and date_time.isValid() else QDateTime.currentDateTime()
        date_widget.setSignalsBlocked(True)
        time_widget.setSignalsBlocked(True)
        date_widget.setDate(dt.date())
        time_widget.setTime(dt.time())
        date_widget.setSignalsBlocked(False)
        time_widget.setSignalsBlocked(False)

    @staticmethod
    def _combine_selected_datetime(date_widget: DateSelector, time_widget: TimeSelector):
        selected_date = date_widget.date()
        selected_time = time_widget.time()
        if not isinstance(selected_date, QDate) or not selected_date.isValid():
            selected_date = QDate.currentDate()
        if not isinstance(selected_time, QTime) or not selected_time.isValid():
            selected_time = QTime.currentTime()
        return QDateTime(selected_date, selected_time).toPyDateTime()

    def _set_filter_range_widgets(self, from_dt: QDateTime, to_dt: QDateTime) -> None:
        start_dt = from_dt if isinstance(from_dt, QDateTime) and from_dt.isValid() else QDateTime.currentDateTime().addDays(-30)
        end_dt = to_dt if isinstance(to_dt, QDateTime) and to_dt.isValid() else QDateTime.currentDateTime()
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt
        self.ds_range.setSignalsBlocked(True)
        self.ts_range.setSignalsBlocked(True)
        self.ds_range.setRange(start_dt.date(), end_dt.date())
        self.ts_range.setRange(start_dt.time(), end_dt.time())
        self.ds_range.setSignalsBlocked(False)
        self.ts_range.setSignalsBlocked(False)

    def _ensure_tx_filters_include_datetime(self, value: Any) -> bool:
        target_dt = self._as_qdatetime(value)
        if not target_dt.isValid():
            return False

        start_py, end_py = self._current_filter_range_datetimes()
        start_dt = self._as_qdatetime(start_py)
        end_dt = self._as_qdatetime(end_py)
        if not start_dt.isValid() or not end_dt.isValid():
            self._set_filter_range_widgets(target_dt, target_dt)
            return True
        if start_dt <= target_dt <= end_dt:
            return False

        next_start = start_dt if target_dt >= start_dt else target_dt
        next_end = end_dt if target_dt <= end_dt else target_dt
        self._set_filter_range_widgets(next_start, next_end)
        return True

    @staticmethod
    def _safe_tx_id(value: Any) -> Optional[int]:
        try:
            tx_id = int(value)
        except Exception:
            return None
        return tx_id if tx_id > 0 else None

    @staticmethod
    def _parse_tx_id_filter_text(value: Any) -> list[int]:
        raw = str(value or "").strip()
        if not raw:
            return []
        for sep in (",", ";", "|", "\n", "\t"):
            raw = raw.replace(sep, " ")
        out: list[int] = []
        for token in raw.split():
            try:
                tx_id = int(token)
            except Exception:
                continue
            if tx_id > 0 and tx_id not in out:
                out.append(tx_id)
        return out

    @staticmethod
    def _direction_token(value: Any) -> str:
        raw = value.value if hasattr(value, "value") else value
        text = str(raw or "").strip().upper()
        if text in {"IN", "IN_"} or text.endswith("IN_") or text.endswith(".IN_") or text.endswith("IN"):
            return "IN_"
        if text == "OUT" or text.endswith(".OUT") or text.endswith("OUT"):
            return "OUT"
        return text

    @staticmethod
    def _reason_token(value: Any) -> str:
        raw = value.value if hasattr(value, "value") else value
        return str(raw or "").strip()

    def _sync_forced_tx_filter_hint(self) -> None:
        self.lbl_forced_tx_filter.hide()
        self.lbl_forced_tx_filter.setText("")

    def apply_forced_tx_filter(self, *, tx_ids: list[int], note: str = "") -> None:
        normalized_ids: set[int] = set()
        for raw_id in (tx_ids or []):
            tx_id = self._safe_tx_id(raw_id)
            if tx_id is not None:
                normalized_ids.add(tx_id)
        self._forced_tx_ids = normalized_ids if normalized_ids else None
        self._forced_item_id = None
        self._forced_tx_filter_note = str(note or "").strip()
        self._sync_forced_tx_filter_hint()
        self._schedule_txs_refresh(immediate=True)

    def apply_forced_item_filter(self, *, item_id: int, note: str = "") -> None:
        try:
            normalized_item_id = int(item_id or 0)
        except Exception:
            normalized_item_id = 0
        if normalized_item_id <= 0:
            self.clear_forced_tx_filter()
            return
        self._forced_tx_ids = None
        self._forced_item_id = normalized_item_id
        self._forced_tx_filter_note = str(note or "").strip()
        self._tx_refresh_suppressed = True
        try:
            self.le_tx_search.clear()
            self.le_filter_tx_ids.clear()
            self._set_switch_data(self.cb_dir, "all")
            self._set_switch_data(self.cb_reason, "all")
            self._set_switch_data(self.cb_filter_warehouse, "all")
            self._set_switch_data(self.cb_filter_currency, "all")
            self._set_switch_data(self.cb_filter_counterparty, "all")
            self._set_switch_data(self.cb_filter_cost, "all")
            self._set_switch_data(self.cb_filter_attachment, "all")
            self._set_switch_data(self.cb_filter_note, "all")
            self._set_switch_data(self.cb_filter_item, normalized_item_id)
        finally:
            self._tx_refresh_suppressed = False
        self._schedule_txs_refresh(immediate=True)

    def clear_forced_tx_filter(self) -> None:
        if not self._forced_tx_ids and not self._forced_tx_filter_note and not self._forced_item_id:
            return
        self._forced_tx_ids = None
        self._forced_item_id = None
        self._forced_tx_filter_note = ""
        self._sync_forced_tx_filter_hint()

    def _current_filter_range_datetimes(self):
        date_from = self.ds_range.dateFrom()
        date_to = self.ds_range.dateTo()
        time_from = self.ts_range.timeFrom()
        time_to = self.ts_range.timeTo()
        if not isinstance(date_from, QDate) or not date_from.isValid():
            date_from = QDate.currentDate()
        if not isinstance(date_to, QDate) or not date_to.isValid():
            date_to = QDate.currentDate()
        if not isinstance(time_from, QTime) or not time_from.isValid():
            time_from = QTime(0, 0, 0)
        if not isinstance(time_to, QTime) or not time_to.isValid():
            time_to = QTime(23, 59, 59)
        start_dt = QDateTime(date_from, time_from)
        end_dt = QDateTime(date_to, time_to)
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt
        return start_dt.toPyDateTime(), end_dt.toPyDateTime()

    def _clear_filters(self):
        self.clear_forced_tx_filter()
        self.le_tx_search.clear()
        self.le_filter_tx_ids.clear()
        self.cb_dir.setCurrentText("Tümü")
        self.cb_reason.setCurrentText("Tümü")
        self.cb_filter_item.setCurrentText("Tümü")
        self.cb_filter_warehouse.setCurrentText("Tümü")
        self.cb_filter_currency.setCurrentText("Tümü")
        self.cb_filter_counterparty.setCurrentText("Tümü")
        self.cb_filter_cost.setCurrentText("Tümü")
        self.cb_filter_attachment.setCurrentText("Tümü")
        self.cb_filter_note.setCurrentText("Tümü")
        self._set_filter_range_widgets(
            QDateTime.currentDateTime().addDays(-30),
            QDateTime.currentDateTime(),
        )
        self._schedule_txs_refresh(immediate=True)

    @staticmethod
    def _set_filter_options(widget: SwitchSelectWidget, values: list[str]):
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
                idx = widget.findData(current_data)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                    restored = True
            if not restored:
                widget.setCurrentIndex(0)

    @staticmethod
    def _set_filter_pair_options(widget: SwitchSelectWidget, values: list[tuple[str, Any]]):
        current_data = widget.currentData()
        with QSignalBlocker(widget):
            widget.clear()
            seen: set[tuple[str, str]] = set()
            for label, data in values:
                text = str(label or "").strip()
                if not text:
                    continue
                key = (text.casefold(), str(data))
                if key in seen:
                    continue
                seen.add(key)
                widget.addItem(text, data)
            restored = False
            if current_data not in (None, "all"):
                idx = widget.findData(current_data)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                    restored = True
            if not restored:
                widget.setCurrentIndex(0)

    def _item_name_from_id(self, item_id: Any) -> str:
        try:
            item_key = int(item_id)
        except Exception:
            return "-"
        return self._item_name_by_id.get(item_key, f"#{item_key}")

    def _warehouse_name_from_id(self, warehouse_id: Any) -> str:
        try:
            warehouse_key = int(warehouse_id)
        except Exception:
            return "-"
        return self._warehouse_name_by_id.get(warehouse_key, f"#{warehouse_key}")

    def _refresh_tx_filter_choices(self, records: list):
        currencies = sorted({
            str(getattr(tx, "currency", "") or "").strip()
            for tx in records
            if str(getattr(tx, "currency", "") or "").strip()
        })
        item_options_set: set[tuple[str, int]] = set()
        warehouse_options_set: set[tuple[str, int]] = set()
        for tx in records:
            raw_item_id = getattr(tx, "item_id", None)
            if raw_item_id is None:
                pass
            else:
                try:
                    item_id = int(raw_item_id)
                except Exception:
                    pass
                else:
                    item_options_set.add((self._item_name_from_id(item_id), item_id))

            raw_warehouse_id = getattr(tx, "warehouse_id", None)
            if raw_warehouse_id is None:
                continue
            try:
                warehouse_id = int(raw_warehouse_id)
            except Exception:
                continue
            warehouse_options_set.add((self._warehouse_name_from_id(warehouse_id), warehouse_id))
        item_options = sorted(item_options_set, key=lambda it: it[0].casefold())
        warehouse_options = sorted(warehouse_options_set, key=lambda it: it[0].casefold())
        counterparties = sorted({
            str(getattr(tx, "counterparty", "") or "").strip()
            for tx in records
            if str(getattr(tx, "counterparty", "") or "").strip()
        })
        self._set_filter_pair_options(self.cb_filter_item, item_options)
        self._set_filter_pair_options(self.cb_filter_warehouse, warehouse_options)
        self._set_filter_options(self.cb_filter_currency, currencies)
        self._set_filter_options(self.cb_filter_counterparty, counterparties)

    def refresh_all(self):
        self._set_list_loading(True)
        try:
            if self._tx_refresh_timer.isActive():
                self._tx_refresh_timer.stop()
            self._invalidate_tx_query_cache()
            items_res = action_list_items()
            self._item_name_by_id = {}
            self._item_unit_by_id = {}
            self._item_image_by_id = {}
            self._item_allow_negative_by_id = {}
            self._item_vat_rate_by_id = {}
            with QSignalBlocker(self.cb_item):
                self.cb_item.clear()
                if items_res.success:
                    for it in (items_res.data.get("records", []) or []):
                        item_id = getattr(it, "pk", None)
                        if item_id in (None, ""):
                            item_id = getattr(it, "id", None)
                        item_name = str(getattr(it, "name", "") or "").strip() or "-"
                        self.cb_item.addItem(f"{item_name} ({getattr(it, 'sku', '') or '-'})", item_id)
                        if item_id is not None:
                            self._item_name_by_id[int(item_id)] = item_name
                            self._item_unit_by_id[int(item_id)] = str(getattr(it, "unit", "") or "").strip()
                            self._item_image_by_id[int(item_id)] = _first_image_path(getattr(it, "image_path", None))
                            self._item_allow_negative_by_id[int(item_id)] = bool(
                                getattr(it, "allow_negative_stock", False)
                            )
                            raw_vat_rate = getattr(it, "vat_rate", None)
                            try:
                                self._item_vat_rate_by_id[int(item_id)] = float(raw_vat_rate) if raw_vat_rate not in (None, "") else None
                            except Exception:
                                self._item_vat_rate_by_id[int(item_id)] = None
                self.cb_item.setCurrentIndex(0)

            wh_res = action_list_warehouses()
            self._warehouse_name_by_id = {}
            with QSignalBlocker(self.cb_wh):
                self.cb_wh.clear()
                if wh_res.success:
                    for wh in (wh_res.data.get("records", []) or []):
                        warehouse_id = getattr(wh, "pk", None)
                        if warehouse_id in (None, ""):
                            warehouse_id = getattr(wh, "id", None)
                        wh_name = str(getattr(wh, "name", "") or "").strip() or "-"
                        self.cb_wh.addItem(wh_name, warehouse_id)
                        if warehouse_id is not None:
                            self._warehouse_name_by_id[int(warehouse_id)] = wh_name
                self.cb_wh.setCurrentIndex(0)

            self._refresh_company_choices()
            self._sync_unit_cost_tax_state()
            self.refresh_balance_and_txs()
        finally:
            self._set_list_loading(False)

    @staticmethod
    def _tx_has_attachments(tx) -> bool:
        raw = getattr(tx, "attachments", None)
        if not raw:
            return False
        if isinstance(raw, list):
            return any(str(v or "").strip() for v in raw)
        raw_text = str(raw or "").strip()
        if not raw_text:
            return False
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, list):
                return any(str(v or "").strip() for v in parsed)
            if isinstance(parsed, str):
                return bool(parsed.strip())
        except Exception:
            pass
        return bool(raw_text)

    def refresh_balance(self):
        item_id = self.cb_item.currentData()
        wh_id = self.cb_wh.currentData()
        if not item_id or not wh_id:
            self.lbl_on_hand.setText("Stok: -")
            self._sync_out_unit_cost_suggestion(force=False)
            return

        item_unit = ""
        try:
            item_unit = str(self._item_unit_by_id.get(int(item_id), "") or "").strip()
        except Exception:
            item_unit = ""

        bal = action_get_on_hand(item_id=item_id, warehouse_id=wh_id)
        if bal.success:
            on_hand = float(bal.data.get("on_hand", 0) or 0)
            qty_text = _fmt_num(on_hand)
            if item_unit:
                qty_text = f"{qty_text} {item_unit}"
            self.lbl_on_hand.setText(f"Stok: {qty_text}")
        else:
            self.lbl_on_hand.setText("Stok: (hesaplanamadı)")
        self._sync_out_unit_cost_suggestion(force=False)

    def refresh_txs_list(self):
        if self._tx_refresh_timer.isActive():
            self._tx_refresh_timer.stop()
        loading_already_active = self._workspace.is_list_loading()
        if not loading_already_active:
            self._set_list_loading(True)
        keep_selected_id = self.txs_list.selected_tx_id()
        keep_bulk_ids = self.txs_list.bulk_selected_ids()
        dir_value = self.cb_dir.currentData()
        direction_filter = None
        if dir_value not in (None, "all"):
            raw_dir = str(dir_value or "").strip().upper()
            if raw_dir in {"IN", "IN_"}:
                direction_filter = "IN_"
            elif raw_dir in {"OUT"}:
                direction_filter = "OUT"
            elif raw_dir:
                direction_filter = raw_dir
        reason_value = self.cb_reason.currentData()
        manual_tx_ids = set(self._parse_tx_id_filter_text(self.le_filter_tx_ids.text()))
        forced_ids = self._forced_tx_ids or set()
        active_tx_ids = manual_tx_ids if manual_tx_ids else forced_ids
        forced_item_id = self._forced_item_id if isinstance(self._forced_item_id, int) and self._forced_item_id > 0 else None
        date_from, date_to = self._current_filter_range_datetimes()
        backend_reason = None if reason_value in (None, "all") else reason_value
        backend_key = (
            tuple(sorted(active_tx_ids)) if active_tx_ids else None,
            forced_item_id,
            direction_filter,
            self._reason_token(backend_reason),
            date_from.isoformat() if date_from is not None else None,
            date_to.isoformat() if date_to is not None else None,
        )

        if backend_key == self._tx_query_cache_key:
            records = list(self._tx_query_cache_records)
        else:
            if active_tx_ids:
                txs = action_list_txs_by_ids(sorted(active_tx_ids))
            else:
                txs = action_list_txs_filtered(
                    item_id=forced_item_id,
                    warehouse_id=None,
                    direction=direction_filter,
                    reason=backend_reason,
                    date_from=date_from,
                    date_to=date_to,
                    # Global search is applied in UI against enriched fields
                    # (item/depo adları vb.). Backend'de tekrar çalıştırma.
                    search=None,
                    limit=5000 if forced_item_id is not None else 500,
                )
            self._last_txs = []
            if not txs.success:
                self._invalidate_tx_query_cache()
                self.txs_list.set_items(
                    [],
                    keep_selected_id=keep_selected_id,
                    keep_bulk_selected_ids=keep_bulk_ids,
                    item_name_by_id=self._item_name_by_id,
                    item_unit_by_id=self._item_unit_by_id,
                    item_image_by_id=self._item_image_by_id,
                    warehouse_name_by_id=self._warehouse_name_by_id,
                )
                self._update_bulk_panel_state()
                self._refresh_left_panel_header()
                self._sync_focus_guidance_state()
                self._update_edit_lock_state()
                self._sync_card_spin_state()
                if not loading_already_active:
                    self._set_list_loading(False)
                return

            records = txs.data.get("records", []) or []
            if active_tx_ids:
                records = [
                    tx for tx in records
                    if self._safe_tx_id(_stock_row_pk(tx)) in active_tx_ids
                ]
                if direction_filter is not None:
                    if direction_filter == "IN_":
                        records = [tx for tx in records if self._direction_token(getattr(tx, "direction", None)) == "IN_"]
                    elif direction_filter == "OUT":
                        records = [tx for tx in records if self._direction_token(getattr(tx, "direction", None)) == "OUT"]
                    else:
                        records = [
                            tx for tx in records
                            if self._direction_token(getattr(tx, "direction", None)) == self._direction_token(direction_filter)
                        ]
                if backend_reason is not None:
                    records = [
                        tx for tx in records
                        if self._reason_token(getattr(tx, "reason", None)) == self._reason_token(backend_reason)
                    ]
            self._tx_query_cache_key = backend_key
            self._tx_query_cache_records = list(records)

        self._last_txs = []
        self._refresh_tx_filter_choices(records)

        item_filter = self.cb_filter_item.currentData()
        if item_filter not in (None, "all"):
            try:
                item_filter_id = int(item_filter)
                records = [
                    tx for tx in records
                    if int(getattr(tx, "item_id", 0) or 0) == item_filter_id
                ]
            except Exception:
                records = []

        warehouse_filter = self.cb_filter_warehouse.currentData()
        if warehouse_filter not in (None, "all"):
            try:
                warehouse_filter_id = int(warehouse_filter)
                records = [
                    tx for tx in records
                    if int(getattr(tx, "warehouse_id", 0) or 0) == warehouse_filter_id
                ]
            except Exception:
                records = []

        currency_filter = self.cb_filter_currency.currentData()
        if currency_filter not in (None, "all"):
            records = [
                tx for tx in records
                if str(getattr(tx, "currency", "") or "").strip().casefold() == str(currency_filter).strip().casefold()
            ]

        cp_filter = self.cb_filter_counterparty.currentData()
        if cp_filter not in (None, "all"):
            records = [
                tx for tx in records
                if str(getattr(tx, "counterparty", "") or "").strip().casefold() == str(cp_filter).strip().casefold()
            ]

        cost_filter = self.cb_filter_cost.currentData()
        if cost_filter == "has":
            records = [tx for tx in records if getattr(tx, "unit_cost", None) is not None]
        elif cost_filter == "none":
            records = [tx for tx in records if getattr(tx, "unit_cost", None) is None]

        attachment_filter = self.cb_filter_attachment.currentData()
        if attachment_filter == "has":
            records = [tx for tx in records if self._tx_has_attachments(tx)]
        elif attachment_filter == "none":
            records = [tx for tx in records if not self._tx_has_attachments(tx)]

        note_filter = self.cb_filter_note.currentData()
        if note_filter == "has":
            records = [tx for tx in records if str(getattr(tx, "note", "") or "").strip()]
        elif note_filter == "none":
            records = [tx for tx in records if not str(getattr(tx, "note", "") or "").strip()]

        q = (self.le_tx_search.text() or "").strip().casefold()
        if q:
            def _hit(t):
                return q in str(t).casefold()
            records = [
                tx for tx in records
                if _hit(getattr(tx, "occurred_at", ""))
                or _hit(_human_tx_direction(getattr(tx, "direction", "")))
                or _hit(_human_tx_reason(getattr(tx, "reason", "")))
                or _hit(self._item_name_from_id(getattr(tx, "item_id", None)))
                or _hit(self._warehouse_name_from_id(getattr(tx, "warehouse_id", None)))
                or _hit(getattr(tx, "qty", ""))
                or _hit(getattr(tx, "unit_cost", ""))
                or _hit(getattr(tx, "currency", ""))
                or _hit(getattr(tx, "counterparty", ""))
                or _hit(getattr(tx, "order_ref", ""))
                or _hit(getattr(tx, "listing_id", ""))
                or _hit(getattr(tx, "map_qty", ""))
                or _hit(getattr(tx, "note", ""))
            ]

        self.txs_list.set_items(
            records,
            keep_selected_id=keep_selected_id,
            keep_bulk_selected_ids=keep_bulk_ids,
            item_name_by_id=self._item_name_by_id,
            item_unit_by_id=self._item_unit_by_id,
            item_image_by_id=self._item_image_by_id,
            warehouse_name_by_id=self._warehouse_name_by_id,
        )
        self._last_txs = list(records)
        self._sync_forced_tx_filter_hint()
        self._update_bulk_panel_state()
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()
        self._sync_card_spin_state()
        if not loading_already_active:
            self._set_list_loading(False)

    def refresh_balance_and_txs(self):
        self.refresh_balance()
        self.refresh_txs_list()

    def export_csv(self):
        if not self._last_txs:
            self.error("Hata", "Dışa aktarılacak hareket bulunamadı.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Excel kaydet", "", "Excel (*.xlsx)")
        if not path:
            return
        res = action_export_txs_excel(txs=self._last_txs, output_path=path)
        if res.success:
            self.info("OK", res.message or "Excel kaydedildi.")
        else:
            self.error("Hata", f"{res.message}\n{res.data}")

    def _update_selected_tx_edit_fields(self):
        selected = self.txs_list.selected_tx()
        if selected is None:
            self.error("Hata", "Güncellenecek bir hareket seçmelisin.")
            return
        tx_id = _stock_row_pk(selected) or 0
        if tx_id <= 0:
            self.error("Hata", "Geçersiz hareket numarası.")
            return

        tx_files = self.tx_file_picker.files()
        payload = json.dumps(tx_files, ensure_ascii=False) if tx_files else None
        unit_cost_input_mode = self._get_unit_cost_tax_mode()
        unit_cost_vat_rate = self._selected_item_vat_rate()
        selected_cost = self._as_positive_float(getattr(selected, "unit_cost", None))
        if selected_cost is not None and unit_cost_input_mode == "net" and unit_cost_vat_rate is None:
            self.error("Hata", "KDV hariç maliyet için stok kartında KDV oranı zorunlu.")
            return

        res = action_update_tx_edit_fields(
            tx_id=tx_id,
            attachments=payload,
            unit_cost_input_mode=unit_cost_input_mode,
            unit_cost_vat_rate=unit_cost_vat_rate,
        )
        if res.success:
            self.info("OK", res.message or "Hareket düzenleme alanları güncellendi.")
            return
        self.error("Hata", f"{res.message}\n{res.data}")

    def on_in(self):
        item_id = self.cb_item.currentData()
        wh_id = self.cb_wh.currentData()
        if item_id in (None, "") or wh_id in (None, ""):
            self.error("Hata", "Ürün ve depo seçmelisin.")
            return

        qty = float(self.sp_qty.value())
        note = (self.le_note.text() or "").strip() or None
        occurred_at = self._combine_selected_datetime(self.ds_occurred_date, self.ts_occurred_time)
        tx_files = self.tx_file_picker.files()

        if not self.le_unit_cost.has_value():
            self.error("Hata", "Giriş için birim maliyet zorunlu.")
            return
        unit_cost = float(self.le_unit_cost.value())
        if unit_cost <= 0:
            self.error("Hata", "Birim maliyet geçerli bir sayı olmalı (örn. 12.5).")
            return

        unit_cost_input_mode = self._get_unit_cost_tax_mode()
        unit_cost_vat_rate = self._selected_item_vat_rate()
        if unit_cost_input_mode == "net" and unit_cost_vat_rate is None:
            self.error("Hata", "KDV hariç maliyet için stok kartında KDV oranı zorunlu.")
            return

        currency = (self.cb_currency.currentText() or "").strip()
        if currency not in CURRENCY_OPTIONS:
            self.error("Hata", "Para birimi listeden seçilmeli.")
            return

        reason = self.cb_tx_reason.currentData()
        res = action_manual_in(
            item_id=item_id,
            warehouse_id=wh_id,
            qty=qty,
            note=note,
            occurred_at=occurred_at,
            unit_cost=unit_cost,
            unit_cost_input_mode=unit_cost_input_mode,
            unit_cost_vat_rate=unit_cost_vat_rate,
            currency=currency,
            counterparty=(self.cb_company.currentText() or "").strip() or None,
            attachments=json.dumps(tx_files) if tx_files else None,
            reason=reason,
        )
        if res.success:
            self._ensure_tx_filters_include_datetime(occurred_at)
            self.tx_file_picker.clearFiles()
            self._reset_form_fields()
            self.info("OK", res.message or "Stok giriş kaydedildi.")
        else:
            self.error("Hata", f"{res.message}\n{res.data}")

    def on_out(self):
        item_id = self.cb_item.currentData()
        wh_id = self.cb_wh.currentData()
        if item_id in (None, "") or wh_id in (None, ""):
            self.error("Hata", "Ürün ve depo seçmelisin.")
            return

        qty = float(self.sp_qty.value())
        note = (self.le_note.text() or "").strip() or None
        occurred_at = self._combine_selected_datetime(self.ds_occurred_date, self.ts_occurred_time)
        tx_files = self.tx_file_picker.files()
        currency = (self.cb_currency.currentText() or "").strip()
        if currency not in CURRENCY_OPTIONS:
            self.error("Hata", "Para birimi listeden seçilmeli.")
            return
        unit_cost = None
        if self.le_unit_cost.has_value():
            unit_cost = float(self.le_unit_cost.value())
            if unit_cost <= 0:
                self.error("Hata", "Birim maliyet geçerli bir sayı olmalı (örn. 12.5).")
                return

        suggested_cost, suggested_currency = self._resolve_out_cost_suggestion()
        self._out_avg_cost_suggestion = suggested_cost
        self._out_avg_currency_suggestion = suggested_currency

        if unit_cost is None and suggested_cost is not None:
            unit_cost = float(suggested_cost)
            if suggested_currency:
                if self.cb_currency.findText(suggested_currency) < 0:
                    self.cb_currency.addItem(suggested_currency, suggested_currency)
                self.cb_currency.setCurrentText(suggested_currency)
                currency = suggested_currency
        elif unit_cost is not None and suggested_cost is not None:
            if not _same_display_cost(unit_cost, suggested_cost):
                warn_text = (
                    "Bu urun/depo icin hareketli ortalama birim maliyet farkli.\n\n"
                    f"Hareketli ortalama: {_fmt_num(suggested_cost)} {suggested_currency}\n"
                    f"Girilen maliyet: {_fmt_num(unit_cost)} {currency}\n\n"
                    "Farklı maliyet kaydı stok maliyet kayıtlarına zarar verebilir.\n"
                    "Bu değerle devam etmek istiyor musun?"
                )
                if not self.confirm("Maliyet Uyarisi", warn_text):
                    return

        reason = self.cb_tx_reason.currentData()
        reason_raw = str(reason or "").strip()
        is_order_out = reason_raw == StockTxReason.order_out.value
        order_ref = (self.le_order_ref.text() or "").strip()
        if is_order_out and not order_ref:
            self.error("Hata", "Sipariş Çıkış için sipariş referansı zorunlu.")
            return

        ref_type = StockReferenceType.none
        ref_id = None
        order_ref_value = None
        allow_negative = False
        if is_order_out:
            ref_type = StockReferenceType.order
            ref_id = order_ref
            order_ref_value = order_ref
            try:
                item_key = int(item_id)
            except Exception:
                item_key = 0
            allow_negative = bool(self._item_allow_negative_by_id.get(item_key, False))

        res = action_manual_out(
            item_id=item_id,
            warehouse_id=wh_id,
            qty=qty,
            note=note,
            occurred_at=occurred_at,
            allow_negative=allow_negative,
            unit_cost=unit_cost,
            currency=currency,
            counterparty=(self.cb_company.currentText() or "").strip() or None,
            attachments=json.dumps(tx_files) if tx_files else None,
            reason=reason,
            reference_type=ref_type,
            reference_id=ref_id,
            order_ref=order_ref_value,
        )
        if res.success:
            self._ensure_tx_filters_include_datetime(occurred_at)
            self.tx_file_picker.clearFiles()
            self._reset_form_fields()
            self.info("OK", res.message or "Stok çıkış kaydedildi.")
        else:
            self.error("Hata", f"{res.message}\n{res.data}")


# =========================================================
# ? Overview Dialog
# =========================================================








