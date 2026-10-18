from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEvent, QTimer, Qt, QSignalBlocker, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from Core.threads.sync_worker import SyncWorker
from Core.views import (
    AppMessageCenter,
    RecordWorkspaceBehaviorAdapter,
    RecordWorkspaceCardRecord,
    RecordWorkspaceListDelegate,
    RecordWorkspaceListModel,
    RecordWorkspaceListWidget,
    RecordWorkspaceScaffold,
    SwitchButton,
    SwitchSelectWidget,
    compose_record_workspace_style,
)
from Feedback.processors.pipeline import MessageHandler
from Feedback.processors.pipeline import Result
from Marketplaces.constants.ui_constants import (
    MARKETPLACE_ACCEPT_BUTTON_TEXT,
    MARKETPLACE_ACCEPT_CONFIRMATION_TEXT,
    MARKETPLACE_ACCEPT_TITLE,
)
from settings import ASSETS_DIR


def _marketplace_action(name: str):
    from Marketplaces.views import actions

    return getattr(actions, name)


def accept_marketplace_record(*args, **kwargs):
    return _marketplace_action("accept_marketplace_record")(*args, **kwargs)


def delete_marketplace(*args, **kwargs):
    return _marketplace_action("delete_marketplace")(*args, **kwargs)


def load_marketplaces(*args, **kwargs):
    return _marketplace_action("load_marketplaces")(*args, **kwargs)


def marketplace_source_filter_options(*args, **kwargs):
    return _marketplace_action("marketplace_source_filter_options")(*args, **kwargs)


def marketplace_status_filter_options(*args, **kwargs):
    return _marketplace_action("marketplace_status_filter_options")(*args, **kwargs)


def save_marketplace(*args, **kwargs):
    return _marketplace_action("save_marketplace")(*args, **kwargs)


def set_marketplaces_active_state(*args, **kwargs):
    return _marketplace_action("set_marketplaces_active_state")(*args, **kwargs)


MARKETPLACES_STYLE = """
QLabel#MarketplaceSourceBadge {
    padding: 4px 8px;
    border-radius: 999px;
    background: rgba(59, 130, 246, 0.10);
    color: #1D4ED8;
    font-size: 10px;
    font-weight: 900;
}
QLabel#MarketplaceCode {
    color: #64748B;
    font-size: 11px;
}
"""


def _resolve_marketplaces_icon_path() -> Path:
    candidates = (
        ASSETS_DIR / "marketplaces-icon.png",
        ASSETS_DIR / "anlik-durum-icon.png",
        ASSETS_DIR / "duzenleme-icon.png",
    )
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _resolve_marketplace_logo_path(raw_value: object) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    normalized = text.replace("\\", "/")
    path = Path(normalized)
    if path.exists():
        return str(path)
    asset_candidate = ASSETS_DIR / path.name
    if asset_candidate.exists():
        return str(asset_candidate)
    return normalized


def marketplaces_icon_path() -> str:
    return str(_resolve_marketplaces_icon_path())


def _bool_label(value: object) -> str:
    return "Açık" if bool(value) else "Kapalı"


@dataclass
class MarketplaceCardRecord(RecordWorkspaceCardRecord):

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "MarketplaceCardRecord":
        code = str(row.get("code") or "").strip().upper()
        label = str(row.get("label") or "").strip() or code or "(İsimsiz Pazaryeri)"
        description = str(row.get("description") or "").strip()
        subtitle = description or "Aciklama yok"
        extra = f"Kod: {code or '-'}"
        return cls(
            orderNumber=code or label,
            title=label,
            subtitle=subtitle,
            extra=extra,
            logo_path=_resolve_marketplace_logo_path(row.get("logoPath")),
            payload=dict(row or {}),
        )


def _marketplace_to_card_record(row: dict[str, Any]) -> MarketplaceCardRecord:
    return MarketplaceCardRecord.from_row(row)


class MarketplacesListDelegate(RecordWorkspaceListDelegate):
    @staticmethod
    def _payload_for(index) -> dict[str, Any]:
        record = index.data(RecordWorkspaceListModel.RecordRole)
        payload = getattr(record, "payload", None)
        return dict(payload or {}) if isinstance(payload, dict) else {}

    def _is_pending_builtin_index(self, index) -> bool:
        payload = self._payload_for(index)
        return bool(payload.get("isBuiltin")) and not bool(payload.get("isBuiltinAccepted"))

    def _is_seed_removed_builtin_index(self, index) -> bool:
        payload = self._payload_for(index)
        return bool(payload.get("isSeedRemoved"))

    def _hook_text(self, index) -> str:
        if self._is_pending_builtin_index(index):
            return MARKETPLACE_ACCEPT_BUTTON_TEXT
        if self._is_seed_removed_builtin_index(index):
            return "Kaydi Sil"
        return super()._hook_text(index)

    def _hook_rect_for_index(self, rect, index, view=None):
        if self._is_pending_builtin_index(index) or self._is_seed_removed_builtin_index(index):
            return self._build_hook_rect(
                rect,
                view=view,
                hook_w=self._hook_width_for_index(index, minimum=88),
                hook_h=34,
            )
        return super()._hook_rect_for_index(rect, index, view)

    def paint(self, painter: QPainter, option, index) -> None:
        if not self._is_pending_builtin_index(index):
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = self._item_rect(option)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected_flag = self._is_selected_index(index)
        active_flag = self._is_active_index(index)

        bg = QColor("#F3F4F6")
        border = QColor("#D1D5DB")
        if hovered:
            bg = QColor("#E5E7EB")
            border = QColor("#CBD5E1")
        if selected_flag or active_flag:
            bg = QColor("#E5E7EB")
            border = QColor("#94A3B8")

        painter.setBrush(bg)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 10, 10)

        if active_flag and self._active_visual_enabled:
            spin_rect = rect.adjusted(1, 1, -1, -1)
            spin_pen = QPen(QColor("#64748B"), 2)
            spin_pen.setStyle(Qt.PenStyle.CustomDashLine)
            spin_pen.setDashPattern([9, 6])
            spin_pen.setDashOffset(-self._spin_phase)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(spin_pen)
            painter.drawRoundedRect(spin_rect, 10, 10)

        hook_rect = self._hook_rect_for_index(rect, index, option.widget)
        icon_rect = self._icon_rect(rect)
        self._paint_card_icon(painter, index, icon_rect)
        x = self._content_left(rect)
        text_width = self._text_width(rect, hook_rect)

        painter.setPen(QColor("#334155"))
        painter.setFont(self._title_font)
        title_rect = rect.adjusted(x - rect.left(), 18, -(rect.width() - text_width - (x - rect.left())), -rect.height() + 38)
        fm = painter.fontMetrics()
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(str(index.data(RecordWorkspaceListModel.TitleRole) or ""), Qt.TextElideMode.ElideRight, title_rect.width()),
        )
        subtitle_rect = rect.adjusted(x - rect.left(), 42, -(rect.width() - text_width - (x - rect.left())), -rect.height() + 60)
        self._draw_labeled_segments_line(
            painter,
            subtitle_rect,
            str(index.data(RecordWorkspaceListModel.SubtitleRole) or ""),
            key_color=QColor("#475569"),
            value_color=QColor("#64748B"),
            point_size=8,
        )
        extra_rect = rect.adjusted(x - rect.left(), 64, -(rect.width() - text_width - (x - rect.left())), -12)
        self._draw_labeled_segments_line(
            painter,
            extra_rect,
            str(index.data(RecordWorkspaceListModel.ExtraRole) or ""),
            key_color=QColor("#475569"),
            value_color=QColor("#6B7280"),
            point_size=8,
        )
        self._paint_hook_button(painter, hook_rect, index=index, row=index.row(), hook_selected=False)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if not self._is_pending_builtin_index(index) and not self._is_seed_removed_builtin_index(index):
            return super().editorEvent(event, model, option, index)
        rect = self._item_rect(option)
        view = option.widget
        hook_rect = self._hook_rect_for_index(rect, index, view)
        if event.type() == QEvent.Type.MouseMove:
            pos = event.position().toPoint()
            hovering = hook_rect.contains(pos)
            if hovering and self._hover_row != index.row():
                self._hover_row = index.row()
                if view:
                    view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    self._update_view_row(view, index, option.rect)
            elif not hovering and self._hover_row == index.row():
                self._hover_row = None
                if view:
                    view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    self._update_view_row(view, index, option.rect)
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if hook_rect.contains(event.position().toPoint()):
                self._pressed_row = index.row()
                if view:
                    self._update_view_row(view, index, option.rect)
                return True
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            was_pressed = self._pressed_row == index.row()
            self._pressed_row = None
            if view:
                self._update_view_row(view, index, option.rect)
            if was_pressed and hook_rect.contains(event.position().toPoint()):
                self._mark_view_action_click_handled(view)
                return bool(self._handle_hook_activated(model, index, True))
        return super().editorEvent(event, model, option, index)


class MarketplacesListWidget(RecordWorkspaceListWidget):
    def __init__(self, parent=None):
        super().__init__(
            parent,
            empty_placeholder_text="Gösterilecek pazaryeri bulunamadı.",
        )
        self._delegate = MarketplacesListDelegate(self, on_select_button=self._on_select_button_clicked)
        self.setItemDelegate(self._delegate)
        self.set_page_size(20)

    def set_marketplaces(self, rows: list[dict[str, Any]]) -> None:
        records = [_marketplace_to_card_record(row) for row in (rows or [])]
        self.set_records(records)
        self.clear_active_record()

    def record_from_payload_key(self, code: str):
        needle = str(code or "").strip().upper()
        for record in self.filtered_records or []:
            payload = getattr(record, "payload", None) or {}
            if str(payload.get("code") or "").strip().upper() == needle:
                return record
        return None

    def selected_payload_codes(self) -> set[str]:
        selected: set[str] = set()
        for record in self.get_selected_records():
            payload = getattr(record, "payload", None) or {}
            code = str(payload.get("code") or "").strip().upper()
            if code:
                selected.add(code)
        return selected

    def restore_selected_payload_codes(self, codes: set[str] | list[str] | tuple[str, ...]) -> None:
        selected_codes = {str(code or "").strip().upper() for code in (codes or []) if str(code or "").strip()}
        changed = False
        for record in self.filtered_records or []:
            payload = getattr(record, "payload", None) or {}
            code = str(payload.get("code") or "").strip().upper()
            should_select = code in selected_codes
            if bool(getattr(record, "_selected", False)) != should_select:
                setattr(record, "_selected", should_select)
                changed = True
        if changed:
            self._build_page()
        else:
            self._emit_selection_signals_if_needed(force=True)


class MarketplacesWorkspaceBehaviorAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, window: "MarketplacesWindow") -> None:
        self.window = window
        self.new_panel_id = None
        self.edit_panel_id = "edit"
        self.bulk_panel_id = "bulk"
        self.clear_active_on_close = True

    @property
    def list_widget(self):
        return self.window.list_widget

    def get_mode(self) -> str:
        return str(getattr(self.window, "_left_mode", "edit") or "edit")

    def set_mode(self, mode: str) -> None:
        self.window._set_left_mode(mode)

    def get_active_key(self) -> str:
        return str(getattr(self.window, "_active_code", "") or "")

    def get_selected_count(self) -> int:
        return len(self.window.list_widget.get_selected_records())

    def get_record_key(self, record) -> str:
        payload = getattr(record, "payload", None) or {}
        return str(payload.get("code") or "")

    def prepare_new(self) -> None:
        self.window._prepare_empty_edit()

    def edit_without_active(self) -> None:
        self.window._prepare_empty_edit()

    def activate_record(self, record) -> None:
        self.window._activate_record_state(record)

    def clear_active(self) -> None:
        self.window._clear_active_record_state()

    def apply_selection(self, record, selected: bool) -> None:
        self.window._workspace_apply_selection(record, bool(selected))

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self.window.list_widget.set_select_button_guide_enabled(enabled)

    def on_state_changed(self) -> None:
        self.window._sync_workspace_state()

    def edit_guidance_message(self) -> str:
        return "Düzenlemek için sağdaki listeden bir pazaryeri seç."

    def bulk_guidance_message(self) -> str:
        return "Toplu işlem için sağdaki listeden en az bir pazaryerini SEÇ ile işaretle."


class MarketplacesWindow(QWidget):
    itemsChanged = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pazaryerleri")
        self.setMinimumSize(1180, 760)
        self.setWindowIcon(QIcon(marketplaces_icon_path()))
        flags = self.windowFlags()
        flags |= Qt.WindowType.WindowMinMaxButtonsHint
        self.setWindowFlags(flags)
        self._first_show_done = False
        self._left_mode = "edit"
        self._active_code = ""
        self._records: list[dict[str, Any]] = []
        self._reload_worker: SyncWorker | None = None
        self._reload_pending = False
        self._reload_seq = 0
        self._reload_timer = QTimer(self)
        self._reload_timer.setInterval(250)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self.request_reload_items)

        workspace_style = compose_record_workspace_style(MARKETPLACES_STYLE)
        self._workspace = RecordWorkspaceScaffold(
            self,
            empty_placeholder_text="Gösterilecek pazaryeri bulunamadı.",
            left_title="Pazaryeri Düzenle",
            left_subtitle="Sağdaki listeden bir pazaryeri seçip etiketini yönet.",
            filters_title="Filtreler",
            filters_subtitle="Yazdıkça otomatik uygular.",
            records_title="Pazaryerleri",
            records_subtitle="Yerleşik ve özelleştirilmiş kanal kayıtları",
            sidebar_buttons=(
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": "Pazaryeri düzenle",
                    "icon_path": str(ASSETS_DIR / "duzenleme-icon.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "bulk",
                    "text": "",
                    "tooltip": "Toplu seçim paneli",
                    "icon_path": str(ASSETS_DIR / "toplu-secim (2).png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
            ),
            shell_kwargs={
                "sidebar_width": 92,
                "left_stick_size": 520,
                "left_collapse_trigger": 430,
                "min_left_width": 380,
                "min_right_width": 340,
                "root_margins": (0, 0, 0, 0),
                "root_spacing": 8,
                "snap_on_drag": True,
            },
            page_size_options=(20, 50, 100),
            style_sheet=workspace_style,
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._workspace)

        self._workspace_shell = self._workspace.shell
        self._panel_sidebar = self._workspace.sidebar
        self._splitter = self._workspace_shell.splitter
        self._editor_scroll = self._workspace.editor_scroll
        self._editor_actions_host = self._workspace.editor_actions_host
        self.bulk_panel = self._workspace.bulk_panel

        self._build_editor_panel()
        self._build_bulk_panel()
        self._build_filters_panel()

        self.list_widget = MarketplacesListWidget(self._workspace.records_card)
        self.list_widget.selection_changed.connect(self._refresh_bulk_summary)
        self.list_widget.page_changed.connect(lambda *_args: self._sync_workspace_summary())
        self._workspace.set_list_widget(self.list_widget)
        self._workspace.set_records_summary_text("0 / 0 kayıt")

        self._workspace_adapter = MarketplacesWorkspaceBehaviorAdapter(self)
        self._workspace_behavior = self._workspace.create_behavior_controller(adapter=self._workspace_adapter)
        self._splitter.setSizes([0, 1280])

        self._prepare_empty_edit()

    def _build_editor_panel(self) -> None:
        form_host = QWidget(self)
        form_host.setObjectName("FormBody")
        form = QFormLayout(form_host)
        form.setContentsMargins(10, 8, 10, 8)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.code_input = QLineEdit(form_host)
        self.code_input.setObjectName("Input")
        self.code_input.setReadOnly(True)

        self.name_input = QLineEdit(form_host)
        self.name_input.setObjectName("Input")
        self.name_input.setPlaceholderText("Pazaryeri etiketi")
        self.name_input.textChanged.connect(self._sync_workspace_summary)

        self.description_input = QPlainTextEdit(form_host)
        self.description_input.setObjectName("MethodText")
        self.description_input.setReadOnly(True)
        self.description_input.setFixedHeight(92)

        self.status_switch = SwitchButton(form_host)
        self.status_switch.setEnabled(False)

        form.addRow("Kod", self.code_input)
        form.addRow("Etiket", self.name_input)
        form.addRow("Açıklama", self.description_input)
        form.addRow("Durum", self._build_status_row())

        self._workspace.set_editor_widget(form_host)

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text="Temizle",
            save_new_text="Güncelle",
            save_edit_text="Güncelle",
        )
        self._workspace.set_editor_action_delete_supported(False)
        self.btn_clear_edit = self._workspace.editor_action_bar.clear_button
        self.btn_save = self._workspace.editor_action_bar.save_button
        self._workspace.editor_action_bar.clearRequested.connect(self._clear_edit_form)
        self._workspace.editor_action_bar.saveRequested.connect(self._save_current_record)

    def _build_bulk_panel(self) -> None:
        bulk_host = QWidget(self)
        layout = QVBoxLayout(bulk_host)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        self.bulk_summary = QLabel("Seçili pazaryeri: 0", bulk_host, objectName="SectionTitle")
        layout.addWidget(self.bulk_summary)

        hint = QLabel("Yerleşik pazaryerlerinin aktifliği sistem varsayılanıdır; bulk işlemler bilgi amaçlıdır.", bulk_host, objectName="Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.btn_bulk_activate = QPushButton("Seçilenleri Aktif Yap", bulk_host)
        self.btn_bulk_activate.setObjectName("Secondary")
        self.btn_bulk_activate.clicked.connect(lambda: self._run_bulk_set_active(True))
        row.addWidget(self.btn_bulk_activate)

        self.btn_bulk_deactivate = QPushButton("Seçilenleri Pasif Yap", bulk_host)
        self.btn_bulk_deactivate.setObjectName("Secondary")
        self.btn_bulk_deactivate.clicked.connect(lambda: self._run_bulk_set_active(False))
        row.addWidget(self.btn_bulk_deactivate)

        self.btn_bulk_clear = QPushButton("Seçimi Temizle", bulk_host)
        self.btn_bulk_clear.setObjectName("Ghost")
        self.btn_bulk_clear.clicked.connect(self._clear_all_selections)
        row.addWidget(self.btn_bulk_clear)
        self.btn_bulk_accept = QPushButton("Önerilenleri Toplu Kabul Et", bulk_host)
        self.btn_bulk_accept.setObjectName("Secondary")
        self.btn_bulk_accept.clicked.connect(self._accept_pending_marketplaces_bulk)
        row.addWidget(self.btn_bulk_accept)

        layout.addLayout(row)
        layout.addStretch(1)

        self._workspace.set_bulk_widget(bulk_host)

    def _build_filters_panel(self) -> None:
        filters_host = QWidget(self)
        layout = QVBoxLayout(filters_host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("Input")
        self.search_input.setPlaceholderText("Genel Ara (kod, etiket, açıklama...)")
        self.search_input.textChanged.connect(self._schedule_reload)
        layout.addWidget(self.search_input)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.filter_status_combo = SwitchSelectWidget(
            self,
            title="Durum",
            all_text="Tümü",
            multi=False,
            include_all=True,
            default_all=True,
        )
        for label, key in marketplace_status_filter_options():
            self.filter_status_combo.addItem(label, key)
        self.filter_status_combo.currentIndexChanged.connect(self.request_reload_items)
        row.addWidget(self.filter_status_combo, 1)

        self.filter_source_combo = SwitchSelectWidget(
            self,
            title="Kaynak",
            all_text="Tümü",
            multi=False,
            include_all=True,
            default_all=True,
        )
        for label, key in marketplace_source_filter_options():
            self.filter_source_combo.addItem(label, key)
        self.filter_source_combo.currentIndexChanged.connect(self.request_reload_items)
        row.addWidget(self.filter_source_combo, 1)

        self.btn_reset_filters = QPushButton("Filtreyi Sıfırla", self)
        self.btn_reset_filters.setObjectName("SoftDanger")
        self.btn_reset_filters.clicked.connect(self._reset_filters)
        row.addWidget(self.btn_reset_filters)

        layout.addLayout(row)
        self._workspace.set_filters_widget(filters_host)

    def _build_status_row(self) -> QWidget:
        host = QWidget(self)
        host.setFixedHeight(max(36, self.status_switch.sizeHint().height()))
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.status_switch, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        return host

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._first_show_done:
            return
        self._first_show_done = True
        self._set_list_loading(True)
        QTimer.singleShot(0, self.request_reload_items)

    def closeEvent(self, event) -> None:
        worker = self._reload_worker
        if worker is not None and worker.isRunning():
            worker.quit()
            worker.wait(1500)
        super().closeEvent(event)

    def _selected_count(self) -> int:
        return len(self.list_widget.get_selected_records())

    def _sync_workspace_summary(self) -> None:
        total = len(self._records)
        selected = self._selected_count()
        active = sum(1 for row in self._records if bool(row.get("isActive")))
        self._workspace.set_records_summary_text(f"{selected} seçili / {total} kayıt")
        self._workspace.set_filters_footer_text(f"Aktif: {active} | Toplam: {total}")
        self._sync_left_header()

    def _refresh_bulk_summary(self) -> None:
        self.bulk_summary.setText(f"Seçili pazaryeri: {self._selected_count()}")
        has_selection = self._selected_count() > 0
        pending_visible = [
            row for row in self._records
            if bool(row.get("isBuiltin")) and not bool(row.get("isBuiltinAccepted"))
        ]
        pending_selected = [
            record for record in self.list_widget.get_selected_records()
            if bool((getattr(record, "payload", None) or {}).get("isBuiltin"))
            and not bool((getattr(record, "payload", None) or {}).get("isBuiltinAccepted"))
        ]
        self.btn_bulk_activate.setEnabled(has_selection)
        self.btn_bulk_deactivate.setEnabled(has_selection)
        self.btn_bulk_clear.setEnabled(has_selection)
        self.btn_bulk_accept.setEnabled(bool(pending_selected or pending_visible))
        self._sync_workspace_summary()

    def _clear_form(self) -> None:
        self.code_input.clear()
        self.name_input.clear()
        self.name_input.setReadOnly(False)
        self.description_input.clear()
        with QSignalBlocker(self.status_switch):
            self.status_switch.setChecked(False)
        self.status_switch.setEnabled(False)
        self.btn_save.setEnabled(True)

    def _clear_edit_form(self) -> None:
        self.name_input.clear()
        self._sync_workspace_summary()

    def _reset_filters(self) -> None:
        self.search_input.clear()
        self.filter_status_combo.setCurrentIndex(0)
        self.filter_source_combo.setCurrentIndex(0)
        self.reload_items()

    def _switch_source_filter_to_saved_if_pending(self) -> None:
        if str(self.filter_source_combo.currentData() or "").strip().lower() != "pending":
            return
        saved_index = self.filter_source_combo.findData("saved")
        if saved_index >= 0:
            self.filter_source_combo.setCurrentIndex(saved_index)

    def _apply_record_to_form(self, row: dict[str, Any] | None) -> None:
        self._clear_form()
        if not row:
            self.name_input.setReadOnly(False)
            self.btn_save.setEnabled(True)
            self._sync_workspace_summary()
            return
        is_pending_builtin = bool(row.get("isBuiltin")) and not bool(row.get("isBuiltinAccepted"))
        self.code_input.setText(str(row.get("code") or "").strip().upper())
        self.name_input.setText(str(row.get("label") or "").strip())
        self.description_input.setPlainText(str(row.get("description") or "").strip())
        with QSignalBlocker(self.status_switch):
            self.status_switch.setChecked(bool(row.get("isActive")))
        self.status_switch.setEnabled(not is_pending_builtin)
        self.name_input.setReadOnly(is_pending_builtin)
        self.btn_save.setEnabled(not is_pending_builtin)
        self._sync_workspace_summary()

    def _collect_payload(self) -> dict[str, Any]:
        return {
            "code": str(self.code_input.text() or "").strip().upper(),
            "label": str(self.name_input.text() or "").strip(),
            "isActive": self.status_switch.isChecked(),
        }

    def _sync_left_header(self) -> None:
        if self._left_mode == "bulk":
            self._workspace.set_left_title("Toplu İşlem")
            self._workspace.set_left_subtitle("Seçilen pazaryerleri için toplu işlem özeti.")
            return
        if self._active_code:
            label = str(self.name_input.text() or "").strip() or "Pazaryeri Düzenle"
            self._workspace.set_left_title(label)
            self._workspace.set_left_subtitle(f"Kod: {self._active_code}")
            return
        self._workspace.set_left_title("Pazaryeri Düzenle")
        self._workspace.set_left_subtitle("Sağdaki listeden bir pazaryeri seçip etiketini yönet.")

    def _sync_left_mode_surface(self) -> None:
        is_bulk = self._left_mode == "bulk"
        self._editor_scroll.setVisible(not is_bulk)
        self.bulk_panel.setVisible(is_bulk)

    def _set_left_mode(self, mode: str) -> None:
        normalized = str(mode or "edit").strip().lower() or "edit"
        self._left_mode = normalized
        self._workspace.set_editor_action_mode("bulk" if normalized == "bulk" else "edit")
        self._sync_left_mode_surface()
        self._sync_workspace_summary()

    def _prepare_empty_edit(self) -> None:
        self._clear_active_record_state()
        self._set_left_mode("edit")

    def _clear_active_record_state(self) -> None:
        self._active_code = ""
        self._clear_form()
        self.list_widget.clear_active_record()

    def _activate_record_state(self, record) -> None:
        payload = getattr(record, "payload", None) or {}
        self._active_code = str(payload.get("code") or "").strip().upper()
        self.list_widget.set_active_record(record)
        self._apply_record_to_form(payload)
        self._set_left_mode("edit")

    def _sync_workspace_state(self) -> None:
        self._sync_left_mode_surface()
        self.list_widget.set_active_spin_allowed(self._left_mode == "edit" and bool(self._active_code))
        self._refresh_bulk_summary()

    def _set_list_loading(self, busy: bool, message: str = "Pazaryerleri yükleniyor...") -> None:
        self._workspace.set_list_loading(bool(busy), message=message)

    def _schedule_reload(self) -> None:
        self._reload_timer.start()

    def _reload_context(self) -> dict[str, Any]:
        return {
            "active_code": str(self._active_code or "").strip().upper(),
            "selected_codes": self.list_widget.selected_payload_codes(),
            "panel_was_open": self._workspace_shell.is_left_panel_open(),
            "previous_mode": str(self._left_mode or "edit").strip().lower() or "edit",
            "params": {
                "search": str(self.search_input.text() or "").strip(),
                "status_filter": str(self.filter_status_combo.currentData() or "all"),
                "source_filter": str(self.filter_source_combo.currentData() or "all"),
            },
        }

    def _apply_reload_result(self, result: Result, context: dict[str, Any]) -> None:
        active_code = str(context.get("active_code") or "").strip().upper()
        selected_codes = context.get("selected_codes") or set()
        panel_was_open = bool(context.get("panel_was_open"))
        previous_mode = str(context.get("previous_mode") or "edit").strip().lower() or "edit"
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            self._records = []
            self.list_widget.set_marketplaces([])
            self._prepare_empty_edit()
            self._refresh_bulk_summary()
            return
        self._records = list((result.data or {}).get("records") or [])
        self.list_widget.set_marketplaces(self._records)
        self.list_widget.restore_selected_payload_codes(selected_codes)
        active_record = self.list_widget.record_from_payload_key(active_code) if active_code else None
        if previous_mode == "bulk" and self._selected_count() > 0:
            self._clear_active_record_state()
            self._set_left_mode("bulk")
            if active_record is not None:
                self._active_code = active_code
                self.list_widget.set_active_record(active_record)
        elif active_record is not None:
            self._activate_record_state(active_record)
        else:
            self._prepare_empty_edit()
        self._refresh_bulk_summary()
        if not panel_was_open:
            self._workspace_behavior.sync_state()
        elif self._left_mode == "bulk" and self._selected_count() > 0:
            self._workspace_behavior.handle_selection_changed()
        else:
            self._workspace_behavior.handle_panel_sidebar_toggled("edit", True)

    def request_reload_items(self, *_args) -> None:
        worker = self._reload_worker
        if worker is not None and worker.isRunning():
            self._reload_pending = True
            return
        self._reload_pending = False
        self._reload_seq += 1
        seq = int(self._reload_seq)
        context = self._reload_context()
        self._set_list_loading(True)
        worker = SyncWorker(load_marketplaces, parent=self, **dict(context.get("params") or {}))
        self._reload_worker = worker

        def _handle_result(result: Result) -> None:
            if seq == self._reload_seq:
                self._apply_reload_result(result, context)

        def _handle_finished() -> None:
            if self._reload_worker is worker:
                self._reload_worker = None
            worker.deleteLater()
            if seq == self._reload_seq:
                self._set_list_loading(False)
            if self._reload_pending:
                self._reload_pending = False
                QTimer.singleShot(0, self.request_reload_items)

        worker.result_ready.connect(_handle_result)
        worker.finished.connect(_handle_finished)
        worker.start()

    def reload_items(self) -> None:
        self._set_list_loading(True)
        try:
            active_code = str(self._active_code or "").strip().upper()
            selected_codes = self.list_widget.selected_payload_codes()
            panel_was_open = self._workspace_shell.is_left_panel_open()
            previous_mode = str(self._left_mode or "edit").strip().lower() or "edit"
            result = load_marketplaces(
                search=str(self.search_input.text() or "").strip(),
                status_filter=str(self.filter_status_combo.currentData() or "all"),
                source_filter=str(self.filter_source_combo.currentData() or "all"),
            )
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self._records = []
                self.list_widget.set_marketplaces([])
                self._prepare_empty_edit()
                self._refresh_bulk_summary()
                return
            self._records = list((result.data or {}).get("records") or [])
            self.list_widget.set_marketplaces(self._records)
            self.list_widget.restore_selected_payload_codes(selected_codes)
            active_record = self.list_widget.record_from_payload_key(active_code) if active_code else None
            if previous_mode == "bulk" and self._selected_count() > 0:
                self._clear_active_record_state()
                self._set_left_mode("bulk")
                if active_record is not None:
                    self._active_code = active_code
                    self.list_widget.set_active_record(active_record)
            elif active_record is not None:
                self._activate_record_state(active_record)
            else:
                self._prepare_empty_edit()
            self._refresh_bulk_summary()
            if not panel_was_open:
                self._workspace_behavior.sync_state()
            elif self._left_mode == "bulk" and self._selected_count() > 0:
                self._workspace_behavior.handle_selection_changed()
            else:
                self._workspace_behavior.handle_panel_sidebar_toggled("edit", True)
        finally:
            self._set_list_loading(False)

    def _save_current_record(self) -> None:
        active_record = self.list_widget.record_from_payload_key(self._active_code)
        active_payload = getattr(active_record, "payload", None) or {}
        if bool(active_payload.get("isBuiltin")) and not bool(active_payload.get("isBuiltinAccepted")):
            MessageHandler.show(
                self,
                Result.fail("Bu kayıt önce kabul edilmelidir.", close_dialog=False),
                only_errors=True,
            )
            return
        result = save_marketplace(payload=self._collect_payload())
        MessageHandler.show(self, result, only_errors=False)
        if not result.success:
            return
        self.itemsChanged.emit()
        self.reload_items()

    def _delete_current_record(self) -> None:
        code = str(self.code_input.text() or "").strip().upper()
        result = delete_marketplace(code=code)
        MessageHandler.show(self, result, only_errors=False)
        if not result.success:
            return
        self.itemsChanged.emit()
        self.reload_items()

    def _run_bulk_set_active(self, is_active: bool) -> None:
        codes = [
            str((getattr(record, "payload", None) or {}).get("code") or "").strip().upper()
            for record in self.list_widget.get_selected_records()
        ]
        codes = [code for code in codes if code]
        result = set_marketplaces_active_state(codes=codes, is_active=is_active)
        MessageHandler.show(self, result, only_errors=False)
        if not result.success:
            return
        self.itemsChanged.emit()
        self.reload_items()

    def _clear_all_selections(self) -> None:
        self.list_widget.clear_selected_records()
        self._refresh_bulk_summary()

    def _clear_active_selection(self) -> None:
        if self._workspace_shell.is_left_panel_open():
            self._workspace_behavior.handle_blank_area_clicked()
            return
        self._prepare_empty_edit()

    def _workspace_apply_selection(self, record, selected: bool) -> None:
        payload = getattr(record, "payload", None) or {}
        if bool(payload.get("isBuiltin")) and not bool(payload.get("isBuiltinAccepted")) and bool(selected):
            self._accept_marketplace(str(payload.get("code") or "").strip().upper())
            return
        if bool(payload.get("isSeedRemoved")) and bool(selected):
            self._delete_seed_removed_marketplace(str(payload.get("code") or "").strip().upper())
            return
        self.list_widget.set_record_selected(record, bool(selected))

    def _accept_marketplace(self, code: str) -> None:
        if not code:
            return
        if not AppMessageCenter.confirm(
            self,
            MARKETPLACE_ACCEPT_TITLE,
            MARKETPLACE_ACCEPT_CONFIRMATION_TEXT,
            default_yes=False,
        ):
            return
        result = accept_marketplace_record(code=code)
        MessageHandler.show(self, result, only_errors=False)
        if not result.success:
            return
        self._switch_source_filter_to_saved_if_pending()
        self.itemsChanged.emit()
        self.reload_items()

    def _delete_seed_removed_marketplace(self, code: str) -> None:
        if not code:
            return
        if not AppMessageCenter.confirm(
            self,
            "Kaydi Sil",
            "Bu yerleşik pazaryeri artık seed katalogda yok. Veritabanından silmek istiyor musun?",
            default_yes=False,
        ):
            return
        result = delete_marketplace(code=code)
        MessageHandler.show(self, result, only_errors=False)
        if not result.success:
            return
        self.itemsChanged.emit()
        self.reload_items()

    def _accept_pending_marketplaces_bulk(self) -> None:
        selected_payloads = [
            dict(getattr(record, "payload", None) or {})
            for record in self.list_widget.get_selected_records()
        ]
        targets = [
            payload for payload in selected_payloads
            if bool(payload.get("isBuiltin")) and not bool(payload.get("isBuiltinAccepted"))
        ]
        if not targets:
            targets = [
                dict(row or {}) for row in self._records
                if bool(row.get("isBuiltin")) and not bool(row.get("isBuiltinAccepted"))
            ]
        if not targets:
            return
        if not AppMessageCenter.confirm(
            self,
            "Toplu Kabul",
            f"{len(targets)} önerilen pazaryerini kullanıma almak istiyor musun?",
            default_yes=False,
        ):
            return
        first_error = ""
        for payload in targets:
            result = accept_marketplace_record(code=str(payload.get("code") or "").strip().upper())
            if not result.success and not first_error:
                first_error = str(result.message or "Bilinmeyen hata")
        self._switch_source_filter_to_saved_if_pending()
        self.itemsChanged.emit()
        self.reload_items()
        if first_error:
            MessageHandler.show(self, Result.fail(first_error, close_dialog=False), only_errors=True)
            return
        MessageHandler.show(self, Result.ok("Önerilen pazaryerleri kullanıma alındı.", close_dialog=False), only_errors=False)
