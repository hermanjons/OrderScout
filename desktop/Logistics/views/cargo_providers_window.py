from __future__ import annotations

import os

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from Core.threads.sync_worker import SyncWorker
from Core.views import (
    AppMessageCenter,
    AnimatedBorderLineEdit,
    FileBadgePicker,
    RECORD_WORKSPACE_STYLE as FINANCE_STYLE,
    RecordWorkspaceBehaviorAdapter,
    RecordWorkspaceCardRecord as OrdersStyleCardRecord,
    RecordWorkspaceListDelegate as OrdersStyleListDelegate,
    RecordWorkspaceListModel as OrdersStyleListModel,
    RecordWorkspaceListWidget as OrdersStyleListWidget,
    RecordWorkspaceScaffold,
    SwitchSelectWidget,
)
from Feedback.processors.pipeline import MessageHandler, Result
from Logistics.constants import ui_constants as logistics_ui
from Logistics.constants import (
    LOGISTICS_CARGO_PROVIDER_ACCEPT_BUTTON_TEXT,
    LOGISTICS_CARGO_PROVIDER_ACCEPT_CONFIRMATION_TEXT,
    LOGISTICS_CARGO_PROVIDER_ACCEPT_TITLE,
)
from settings import ASSETS_DIR


def _logistics_action(name: str):
    from Logistics.views import actions

    return getattr(actions, name)


def _default_cargo_provider_logo() -> str:
    from Logistics.constants.catalog_constants import LOGISTICS_DEFAULT_CARGO_PROVIDER_LOGO

    return LOGISTICS_DEFAULT_CARGO_PROVIDER_LOGO


def accept_logistics_cargo_provider_record(*args, **kwargs):
    return _logistics_action("accept_logistics_cargo_provider_record")(*args, **kwargs)


def delete_logistics_cargo_provider_record(*args, **kwargs):
    return _logistics_action("delete_logistics_cargo_provider_record")(*args, **kwargs)


def load_logistics_cargo_providers(*args, **kwargs):
    return _logistics_action("load_logistics_cargo_providers")(*args, **kwargs)


def logistics_cargo_provider_platform_options(*args, **kwargs):
    return _logistics_action("logistics_cargo_provider_platform_options")(*args, **kwargs)


def save_logistics_cargo_provider_record(*args, **kwargs):
    return _logistics_action("save_logistics_cargo_provider_record")(*args, **kwargs)


def _compact_text(value) -> str:
    return str(value or "").strip()


class LogisticsCargoProvidersListDelegate(OrdersStyleListDelegate):
    @staticmethod
    def _payload_for(index) -> dict[str, object]:
        record = index.data(OrdersStyleListModel.RecordRole)
        payload = getattr(record, "payload", None)
        return dict(payload or {}) if isinstance(payload, dict) else {}

    def _is_pending_builtin_index(self, index) -> bool:
        payload = self._payload_for(index)
        return bool(payload.get("isBuiltin")) and not bool(payload.get("isBuiltinAccepted"))

    def _hook_text(self, index) -> str:
        if self._is_pending_builtin_index(index):
            return LOGISTICS_CARGO_PROVIDER_ACCEPT_BUTTON_TEXT
        return super()._hook_text(index)

    def _hook_rect_for_index(self, rect, index, view=None):
        if self._is_pending_builtin_index(index):
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
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title_rect = rect.adjusted(x - rect.left(), 18, -(rect.width() - text_width - (x - rect.left())), -rect.height() + 38)
        fm = painter.fontMetrics()
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(str(index.data(OrdersStyleListModel.TitleRole) or ""), Qt.TextElideMode.ElideRight, title_rect.width()),
        )
        subtitle_rect = rect.adjusted(x - rect.left(), 42, -(rect.width() - text_width - (x - rect.left())), -rect.height() + 60)
        self._draw_labeled_segments_line(
            painter,
            subtitle_rect,
            str(index.data(OrdersStyleListModel.SubtitleRole) or ""),
            key_color=QColor("#475569"),
            value_color=QColor("#64748B"),
            point_size=8,
        )
        extra_rect = rect.adjusted(x - rect.left(), 64, -(rect.width() - text_width - (x - rect.left())), -12)
        self._draw_labeled_segments_line(
            painter,
            extra_rect,
            str(index.data(OrdersStyleListModel.ExtraRole) or ""),
            key_color=QColor("#475569"),
            value_color=QColor("#6B7280"),
            point_size=8,
        )
        self._paint_hook_button(painter, hook_rect, index=index, row=index.row(), hook_selected=False)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if not self._is_pending_builtin_index(index):
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


class LogisticsCargoProvidersWorkspaceAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, window: "LogisticsCargoProvidersFormWindow") -> None:
        self.window = window

    @property
    def list_widget(self):
        return self.window.list_widget

    def get_mode(self) -> str:
        return str(getattr(self.window, "_left_mode", "edit") or "edit")

    def set_mode(self, mode: str) -> None:
        self.window._set_left_mode(mode)

    def get_active_key(self) -> str:
        return str(getattr(self.window, "_active_key", "") or "")

    def get_selected_count(self) -> int:
        return len(self.window._selected_keys)

    def get_record_key(self, record) -> str:
        return str(self.window._record_key(record) or "")

    def prepare_new(self) -> None:
        self.window._reset_form(open_panel=False)

    def edit_without_active(self) -> None:
        self.window._show_empty_edit_state()

    def activate_record(self, record) -> None:
        self.window._workspace_activate_record(record)

    def clear_active(self) -> None:
        self.window._workspace_clear_active_record()

    def apply_selection(self, record, selected: bool) -> None:
        self.window._workspace_apply_selection(record, selected)

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self.window.list_widget.set_select_button_guide_enabled(bool(enabled))

    def on_state_changed(self) -> None:
        self.window._on_workspace_state_changed()

    def open_panel(self, shell) -> None:
        _ = shell
        self.window._open_left_panel()

    def close_panel(self, shell) -> None:
        _ = shell
        self.window._close_left_panel()

    def edit_guidance_message(self) -> str:
        return logistics_ui.LOGISTICS_PROVIDERS_EDIT_GUIDANCE

    def bulk_guidance_message(self) -> str:
        return logistics_ui.LOGISTICS_PROVIDERS_BULK_GUIDANCE


class LogisticsCargoProvidersFormWindow(QWidget):
    itemsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("FinanceRoot")
        self.setStyleSheet(FINANCE_STYLE)
        self.setWindowTitle(logistics_ui.LOGISTICS_PROVIDERS_WINDOW_TITLE)
        self.setWindowIcon(QIcon(os.path.join(ASSETS_DIR, "logistics-cargo-providers-icon.png")))
        self.setGeometry(240, 120, 1480, 860)

        self._has_loaded_once = False
        self._records: list[dict[str, object]] = []
        self._record_map: dict[str, dict[str, object]] = {}
        self._active_key: str = ""
        self._selected_keys: set[str] = set()
        self._editing_record: dict[str, object] | None = None
        self._left_mode = "new"
        self._left_stick_size = 560
        self._page_size = 20
        self._reload_worker: SyncWorker | None = None
        self._reload_pending = False
        self._reload_seq = 0

        self._search_timer = QTimer(self)
        self._search_timer.setInterval(250)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.request_reload_items)

        self._build_ui()

    def _build_ui(self) -> None:
        self._workspace = RecordWorkspaceScaffold(
            self,
            empty_placeholder_text="Gösterilecek kargo firması bulunamadı.",
            left_title="Yeni Ekle",
            left_subtitle="Yeni kargo firması oluştur veya sağdaki listeden bir kayıt seçip düzenle.",
            filters_title="Filtreler",
            filters_subtitle="Yazdıkça otomatik uygular.",
            records_title="Kargo Firmaları",
            records_subtitle="Lojistik kargo firma kayıtları",
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": "Yeni kargo firması",
                    "icon_path": str(ASSETS_DIR / "yeni-kayit.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": "Kargo firması düzenle",
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
                "left_stick_size": self._left_stick_size,
                "left_collapse_trigger": 440,
                "min_left_width": 360,
                "min_right_width": 320,
                "root_margins": (0, 0, 0, 0),
                "root_spacing": 8,
                "snap_on_drag": False,
            },
            page_size_options=(20, 50, 100),
            style_sheet=FINANCE_STYLE,
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._workspace)

        self._workspace_shell = self._workspace.shell
        self._panel_sidebar = self._workspace.sidebar
        self.left_panel_title = self._workspace.left_card.title_label
        self.left_panel_hint = self._workspace.left_card.subtitle_label
        self.editor_scroll = self._workspace.editor_scroll
        self.editor_actions_wrap = self._workspace.editor_actions_host
        self.bulk_panel = self._workspace.bulk_panel

        self._build_editor_panel()
        self._build_filters_panel()
        self._build_records_panel()

        self._workspace_adapter = LogisticsCargoProvidersWorkspaceAdapter(self)
        self._workspace_controller = self._workspace.create_behavior_controller(adapter=self._workspace_adapter)
        self._reset_form(open_panel=False)

    def _build_editor_panel(self) -> None:
        editor_host = QWidget(self._workspace.editor_host)
        editor_host.setObjectName("FormBody")
        editor_shell = QVBoxLayout(editor_host)
        editor_shell.setContentsMargins(0, 0, 0, 0)
        editor_shell.setSpacing(0)
        editor_layout = QFormLayout()
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setHorizontalSpacing(12)
        editor_layout.setVerticalSpacing(10)
        editor_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        editor_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        editor_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        editor_shell.addLayout(editor_layout)
        editor_shell.addStretch(1)

        self.input_name = AnimatedBorderLineEdit(self)
        self.input_name.setPlaceholderText(logistics_ui.LOGISTICS_PROVIDERS_NAME_PLACEHOLDER)
        self.input_name.setMinimumHeight(42)
        editor_layout.addRow(QLabel(logistics_ui.LOGISTICS_PROVIDERS_NAME_LABEL, objectName="FieldLabel"), self.input_name)

        self.input_platform = SwitchSelectWidget(
            self,
            multi=False,
            include_all=False,
            empty_text="Seçiniz",
            allow_empty=True,
            search_enabled=True,
        )
        self.input_platform.setPlaceholderText(logistics_ui.LOGISTICS_PROVIDERS_PLATFORM_PLACEHOLDER)
        self.input_platform.setMinimumHeight(42)
        self.input_platform.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for label, code in logistics_cargo_provider_platform_options(include_all=False):
            self.input_platform.addItem(label, code)
        self.input_platform.setLockOnDisabled(True)
        editor_layout.addRow(QLabel(logistics_ui.LOGISTICS_PROVIDERS_PLATFORM_LABEL, objectName="FieldLabel"), self.input_platform)

        self.input_code = AnimatedBorderLineEdit(self)
        self.input_code.setPlaceholderText(logistics_ui.LOGISTICS_PROVIDERS_CODE_PLACEHOLDER)
        self.input_code.setMinimumHeight(42)
        self.input_code.setLockOnDisabled(True)
        editor_layout.addRow(QLabel(logistics_ui.LOGISTICS_PROVIDERS_CODE_LABEL, objectName="FieldLabel"), self.input_code)

        self.logo_selector = FileBadgePicker(
            self,
            button_text="Logo Seç",
            dialog_title="Kargo Firması Logosu Seç",
            dialog_filter="Görseller (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
            allow_multiple=False,
            allowed_extensions=[".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"],
            show_clear_button=True,
        )
        self.logo_selector.setLockOnDisabled(True)
        editor_layout.addRow(QLabel(logistics_ui.LOGISTICS_PROVIDERS_LOGO_LABEL, objectName="FieldLabel"), self.logo_selector)

        self.input_note = QPlainTextEdit(self)
        self.input_note.setObjectName("MethodText")
        self.input_note.setPlaceholderText(logistics_ui.LOGISTICS_PROVIDERS_NOTE_PLACEHOLDER)
        self.input_note.setMinimumHeight(120)
        self.input_note.setMaximumHeight(120)
        editor_layout.addRow(QLabel(logistics_ui.LOGISTICS_PROVIDERS_NOTE_LABEL, objectName="FieldLabel"), self.input_note)

        self._workspace.set_editor_widget(editor_host)

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text="Formu Temizle",
            save_new_text="Kargo Firmasını Kaydet",
            save_edit_text="Güncelle",
            delete_text="Sil",
        )
        self.btn_reset_form = self._workspace.editor_action_bar.clear_button
        self.btn_delete_provider = self._workspace.editor_action_bar.delete_button
        self.btn_save_provider = self._workspace.editor_action_bar.save_button
        self._workspace.editor_action_bar.clearRequested.connect(self._reset_form)
        self._workspace.editor_action_bar.deleteRequested.connect(self._delete_active_item)
        self._workspace.editor_action_bar.saveRequested.connect(self._save_item)

        bulk_content = QWidget(self.bulk_panel)
        bulk_layout = QVBoxLayout(bulk_content)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.setSpacing(8)
        bulk_layout.addWidget(QLabel(logistics_ui.LOGISTICS_PROVIDERS_BULK_TITLE, objectName="SectionTitle"))
        self.bulk_summary_label = QLabel(
            logistics_ui.LOGISTICS_PROVIDERS_SELECTED_COUNT_TEMPLATE.format(count=0),
            objectName="StatusInfo",
        )
        bulk_layout.addWidget(self.bulk_summary_label)
        bulk_hint = QLabel(logistics_ui.LOGISTICS_PROVIDERS_BULK_HINT, objectName="Muted")
        bulk_hint.setWordWrap(True)
        bulk_layout.addWidget(bulk_hint)
        self.btn_accept_selected = QPushButton(logistics_ui.LOGISTICS_PROVIDERS_BULK_ACCEPT_TEXT, bulk_content)
        self.btn_accept_selected.setObjectName("Secondary")
        self.btn_accept_selected.clicked.connect(self._accept_pending_providers_bulk)
        bulk_layout.addWidget(self.btn_accept_selected)
        self.btn_clear_selection = QPushButton(logistics_ui.LOGISTICS_PROVIDERS_BULK_CLEAR_TEXT, bulk_content)
        self.btn_clear_selection.setObjectName("Ghost")
        self.btn_clear_selection.clicked.connect(self._clear_all_selections)
        bulk_layout.addWidget(self.btn_clear_selection)
        bulk_layout.addStretch(1)
        self._workspace.set_bulk_widget(bulk_content)

    def _build_filters_panel(self) -> None:
        filters_host = QWidget(self)
        filter_layout = QVBoxLayout(filters_host)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(10)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(10)
        self.search_input = AnimatedBorderLineEdit(self)
        self.search_input.setPlaceholderText(logistics_ui.LOGISTICS_PROVIDERS_SEARCH_PLACEHOLDER)
        self.search_input.setMinimumHeight(42)
        self.search_input.textChanged.connect(self._schedule_reload)
        search_row.addWidget(self.search_input, 1)

        self.btn_reset_filters = QPushButton(logistics_ui.LOGISTICS_FILTER_CLEAR_TEXT, self)
        self.btn_reset_filters.setObjectName("SoftDanger")
        self.btn_reset_filters.clicked.connect(self._reset_filters)
        search_row.addWidget(self.btn_reset_filters, 0, alignment=Qt.AlignmentFlag.AlignRight)
        filter_layout.addLayout(search_row)

        self.platform_filter = SwitchSelectWidget(
            self,
            title=logistics_ui.LOGISTICS_PROVIDERS_PLATFORM_LABEL,
            all_text=logistics_ui.LOGISTICS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
            search_enabled=True,
        )
        for label, key in logistics_cargo_provider_platform_options(include_all=False):
            self.platform_filter.addItem(label, key)
        self.platform_filter.currentIndexChanged.connect(self.request_reload_items)
        filter_layout.addWidget(self.platform_filter)
        self.source_filter = SwitchSelectWidget(
            self,
            title="Kaynak",
            all_text=logistics_ui.LOGISTICS_FILTER_ALL_TEXT,
            multi=False,
            include_all=True,
            default_all=True,
            search_enabled=False,
        )
        self.source_filter.addItem(logistics_ui.LOGISTICS_FILTER_ALL_TEXT, "")
        self.source_filter.addItem(logistics_ui.LOGISTICS_FILTER_PENDING_TEXT, logistics_ui.LOGISTICS_FILTER_PENDING_VALUE)
        self.source_filter.addItem(logistics_ui.LOGISTICS_FILTER_SAVED_TEXT, logistics_ui.LOGISTICS_FILTER_SAVED_VALUE)
        self.source_filter.currentIndexChanged.connect(self.request_reload_items)
        filter_layout.addWidget(self.source_filter)

        self.filter_summary_label = QLabel(logistics_ui.LOGISTICS_PROVIDERS_TOTAL_TEMPLATE.format(count=0), objectName="StatusInfo")
        filter_layout.addWidget(self.filter_summary_label)
        self._workspace.set_filters_widget(filters_host)

    def _build_records_panel(self) -> None:
        self.list_widget = OrdersStyleListWidget(
            self._workspace.records_card.body_host,
            empty_placeholder_text="Gösterilecek kargo firması bulunamadı.",
        )
        self.list_widget._delegate = LogisticsCargoProvidersListDelegate(
            self.list_widget,
            on_select_button=self.list_widget._on_select_button_clicked,
        )
        self.list_widget.setItemDelegate(self.list_widget._delegate)
        self.list_widget.page_changed.connect(lambda *_args: self._update_pagination_ui())
        self.list_widget.selection_changed.connect(self._on_card_selection_changed)
        self._workspace.set_list_widget(self.list_widget)
        self.btn_bulk_select_toggle = self._workspace.footer_bar.select_toggle
        self._workspace.set_records_summary_text("0 / 0 kayıt")
        self._workspace.set_filters_footer_text(logistics_ui.LOGISTICS_PROVIDERS_TOTAL_TEMPLATE.format(count=0))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._has_loaded_once:
            self._set_list_loading(True)
            QTimer.singleShot(0, self.request_reload_items)
            self._close_left_panel()
            self._has_loaded_once = True

    def closeEvent(self, event) -> None:
        worker = self._reload_worker
        if worker is not None and worker.isRunning():
            worker.quit()
            worker.wait(1500)
        super().closeEvent(event)

    def _schedule_reload(self) -> None:
        self._search_timer.start()

    def _is_left_panel_open(self) -> bool:
        return self._workspace_shell.is_left_panel_open()

    def _open_left_panel(self) -> None:
        self._workspace_shell.open_left_panel(min_left=360, min_right=320)

    def _close_left_panel(self) -> None:
        self._workspace_shell.close_left_panel()

    @staticmethod
    def _record_key(record: OrdersStyleCardRecord | dict | None) -> str:
        if isinstance(record, OrdersStyleCardRecord):
            return str(getattr(record, "orderNumber", "") or "").strip()
        if isinstance(record, dict):
            return _compact_text(record.get("key"))
        return ""

    def _find_record_by_key(self, key: str) -> dict[str, object] | None:
        return self._record_map.get(_compact_text(key))

    def _build_card_record(self, record: dict[str, object]) -> OrdersStyleCardRecord:
        source_note = _compact_text(record.get("sourceNote"))
        extra = f"Kaynak: {_compact_text(record.get('sourceLabel')) or 'Lojistik JSON'}"
        if source_note:
            extra = f"{source_note} | {extra}"
        logo_path = _compact_text(record.get("logoPath")) or _default_cargo_provider_logo()
        return OrdersStyleCardRecord(
            orderNumber=_compact_text(record.get("key")),
            title=_compact_text(record.get("cargoProviderName")) or "-",
            subtitle=(
                f"Platform: {_compact_text(record.get('platformLabel')) or '-'} | "
                f"Kod: {_compact_text(record.get('cargoProviderCode')) or '-'}"
            ),
            extra=extra,
            logo_path=logo_path,
            payload=record,
            _selected=_compact_text(record.get("key")) in self._selected_keys,
        )

    def _set_platform_value(self, platform_code: str) -> None:
        idx = self.input_platform.findData(_compact_text(platform_code).upper())
        self.input_platform.setCurrentIndex(idx if idx >= 0 else -1)

    def _set_logo_value(self, logo_path: str | None) -> None:
        current_logo = _compact_text(logo_path) or _default_cargo_provider_logo()
        self.logo_selector.setFiles([current_logo], emit_signal=False)

    def _refresh_left_panel_header(self) -> None:
        title = "Yeni Ekle"
        subtitle = "Yeni kargo firması oluştur veya sağdaki listeden bir kayıt seçip düzenle."
        if self._left_mode == "bulk":
            title = "Toplu Seçim"
            subtitle = "Toplu seçim için sağdaki listeden en az bir firmayı SEÇ ile işaretle."
        elif self._left_mode == "edit":
            title = "Düzenle"
            if self._editing_record:
                is_builtin = bool(self._editing_record.get("isBuiltin"))
                subtitle = (
                    "JSON kayıtlarında ad ve not değiştirilebilir."
                    if is_builtin
                    else f"Seçili firma: {_compact_text(self._editing_record.get('cargoProviderName')) or '-'}"
                )
            else:
                subtitle = "Düzenlemek için sağdaki listeden bir kargo firması seç."
        self.left_panel_title.setText(title)
        self.left_panel_hint.setText(subtitle)
        self._workspace.set_left_title(title)
        self._workspace.set_left_subtitle(subtitle)

    def _set_left_mode(self, mode: str) -> None:
        normalized = _compact_text(mode).lower() or "new"
        if normalized not in {"new", "edit", "bulk"}:
            normalized = "new"
        self._left_mode = normalized
        self._workspace.set_editor_action_mode(normalized)
        show_editor = normalized in {"new", "edit"}
        self.editor_scroll.setVisible(show_editor)
        self.editor_actions_wrap.setVisible(show_editor)
        self.bulk_panel.setVisible(not show_editor)
        can_delete = bool(self._editing_record and self._editing_record.get("canDelete"))
        self._workspace.set_editor_action_delete_available(show_editor and normalized == "edit" and can_delete)
        self._refresh_left_panel_header()
        self._workspace.schedule_editor_layout_refresh()

    def _set_active_spin_enabled(self) -> None:
        enabled = bool(self._active_key) and self._is_left_panel_open() and self._left_mode == "edit"
        self.list_widget.set_active_spin_allowed(enabled)

    def _clear_form_fields(self) -> None:
        self.input_name.clear()
        self.input_name.setEnabled(True)
        self.input_platform.setEnabled(True)
        self.input_platform.setCurrentIndex(-1)
        self.input_code.clear()
        self.input_code.setEnabled(True)
        self.logo_selector.setEnabled(True)
        self.logo_selector.clearFiles()
        self.input_note.setEnabled(True)
        self.input_note.clear()
        self.btn_save_provider.setEnabled(True)
        self._workspace.set_editor_action_delete_available(False)

    def _reset_form(self, *, open_panel: bool = True) -> None:
        self._editing_record = None
        self._active_key = ""
        self._set_left_mode("new")
        self._clear_form_fields()
        self.list_widget.clear_active_record()
        self._sync_card_states()
        if open_panel:
            self._open_left_panel()

    def _show_empty_edit_state(self) -> None:
        self._editing_record = None
        self._active_key = ""
        self._set_left_mode("edit")
        self._clear_form_fields()
        self.list_widget.clear_active_record()
        self._sync_card_states()

    def _load_form(self, record: dict[str, object], *, open_panel: bool = True) -> None:
        self._editing_record = dict(record or {})
        self._active_key = _compact_text(record.get("key"))
        is_builtin = bool(record.get("isBuiltin"))
        is_pending_builtin = is_builtin and not bool(record.get("isBuiltinAccepted"))

        self._set_left_mode("edit")
        self.input_name.setText(_compact_text(record.get("cargoProviderName")))
        self.input_name.setEnabled(not is_pending_builtin)
        self._set_platform_value(_compact_text(record.get("platformCode")))
        self.input_platform.setEnabled(not is_builtin and not is_pending_builtin)
        self.input_code.setText(_compact_text(record.get("cargoProviderCode")))
        self.input_code.setEnabled(not is_builtin and not is_pending_builtin)
        self._set_logo_value(_compact_text(record.get("logoPath")) or None)
        self.logo_selector.setEnabled(not is_builtin and not is_pending_builtin)
        self.input_note.setPlainText(_compact_text(record.get("note")))
        self.input_note.setEnabled(not is_pending_builtin)
        self.btn_save_provider.setEnabled(not is_pending_builtin)
        self._workspace.set_editor_action_delete_available(bool(record.get("canDelete")) and not is_pending_builtin)
        self._sync_card_states()
        if open_panel:
            self._open_left_panel()

    def _workspace_clear_active_record(self) -> None:
        self._show_empty_edit_state()

    def _workspace_activate_record(self, record: OrdersStyleCardRecord) -> None:
        row = record.payload if isinstance(record.payload, dict) else self._find_record_by_key(self._record_key(record))
        if row is None:
            return
        self._load_form(dict(row), open_panel=False)
        self.list_widget.set_active_record(record)
        self._sync_card_states()

    def _workspace_apply_selection(self, record: OrdersStyleCardRecord, selected: bool) -> None:
        key = self._record_key(record)
        if not key:
            return
        payload = dict(getattr(record, "payload", None) or {})
        if bool(payload.get("isBuiltin")) and not bool(payload.get("isBuiltinAccepted")) and bool(selected):
            self._accept_builtin_provider(payload)
            return
        if selected:
            self._selected_keys.add(key)
        else:
            self._selected_keys.discard(key)
        self._sync_bulk_summary()
        self._sync_card_states()

    def _on_workspace_state_changed(self) -> None:
        self._refresh_left_panel_header()
        self._workspace.set_filters_footer_text(self.filter_summary_label.text())
        self._set_active_spin_enabled()

    def _collect_form_payload(self) -> dict[str, object]:
        record = dict(self._editing_record or {})
        logo_files = self.logo_selector.files()
        logo_path = _compact_text(logo_files[0]) if logo_files else None
        payload = {
            "pk": int(record.get("pk") or 0),
            "key": _compact_text(record.get("key")),
            "cargoProviderName": _compact_text(self.input_name.text()),
            "platformCode": _compact_text(self.input_platform.currentData() or record.get("platformCode")).upper(),
            "cargoProviderCode": _compact_text(self.input_code.text() or record.get("cargoProviderCode")).upper(),
            "note": _compact_text(self.input_note.toPlainText()) or None,
            "logoPath": logo_path,
            "isBuiltin": bool(record.get("isBuiltin")),
            "hasUserOverride": bool(record.get("hasUserOverride")),
            "canEditIdentity": bool(record.get("canEditIdentity", not bool(record.get("isBuiltin")))),
        }
        if payload["isBuiltin"]:
            payload["logoPath"] = None
        return payload

    def _save_item(self) -> None:
        payload = self._collect_form_payload()
        if bool(payload.get("isBuiltin")) and not bool((self._editing_record or {}).get("isBuiltinAccepted")):
            MessageHandler.show(self, Result.fail("Bu kayıt önce kabul edilmelidir.", close_dialog=False), only_errors=True)
            return
        result = save_logistics_cargo_provider_record(payload)
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        match_key = f"{_compact_text(payload.get('platformCode')).upper()}:{_compact_text(payload.get('cargoProviderCode')).upper()}"
        self.reload_items(active_key=match_key, preserve_page=True)
        MessageHandler.show(self, result, only_errors=False)
        self.itemsChanged.emit()

    def _delete_active_item(self) -> None:
        if not self._editing_record:
            return
        result = delete_logistics_cargo_provider_record(dict(self._editing_record))
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        removed_key = _compact_text((self._editing_record or {}).get("key"))
        self._selected_keys.discard(removed_key)
        self._reset_form(open_panel=False)
        self.reload_items()
        MessageHandler.show(self, result, only_errors=False)
        self.itemsChanged.emit()

    def _reset_filters(self) -> None:
        self.search_input.clear()
        self.platform_filter.setCurrentIndex(0)
        self.source_filter.setCurrentIndex(0)
        self.reload_items()

    def _switch_source_filter_to_saved_if_pending(self) -> None:
        if str(self.source_filter.currentData() or "").strip().lower() != "pending":
            return
        saved_index = self.source_filter.findData("saved")
        if saved_index >= 0:
            self.source_filter.setCurrentIndex(saved_index)

    def _accept_builtin_provider(self, payload: dict[str, object]) -> None:
        if not AppMessageCenter.confirm(
            self,
            LOGISTICS_CARGO_PROVIDER_ACCEPT_TITLE,
            LOGISTICS_CARGO_PROVIDER_ACCEPT_CONFIRMATION_TEXT,
            default_yes=False,
        ):
            return
        result = accept_logistics_cargo_provider_record(dict(payload or {}))
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return
        self._switch_source_filter_to_saved_if_pending()
        self.reload_items(active_key=_compact_text(payload.get("key")), preserve_page=True)
        MessageHandler.show(self, result, only_errors=False)
        self.itemsChanged.emit()

    def _accept_pending_providers_bulk(self) -> None:
        target_keys = [
            key for key in self._selected_keys
            if bool((self._record_map.get(key) or {}).get("isBuiltin"))
            and not bool((self._record_map.get(key) or {}).get("isBuiltinAccepted"))
        ]
        if not target_keys:
            target_keys = [
                self._record_key(row)
                for row in self._records
                if self._record_key(row)
                and bool(row.get("isBuiltin"))
                and not bool(row.get("isBuiltinAccepted"))
            ]
        target_payloads = [dict(self._record_map.get(key) or {}) for key in target_keys if self._record_map.get(key)]
        if not target_payloads:
            return
        if not AppMessageCenter.confirm(
            self,
            "Toplu Kabul",
            f"{len(target_payloads)} önerilen kargo firmasını kullanıma almak istiyor musun?",
            default_yes=False,
        ):
            return
        first_error = ""
        for payload in target_payloads:
            result = accept_logistics_cargo_provider_record(dict(payload or {}))
            if not result.success and not first_error:
                first_error = str(result.message or "Bilinmeyen hata")
        self._switch_source_filter_to_saved_if_pending()
        self.reload_items(preserve_page=True)
        if first_error:
            MessageHandler.show(self, Result.fail(first_error, close_dialog=False), only_errors=True)
            return
        MessageHandler.show(self, Result.ok("Önerilen kargo firmaları kullanıma alındı.", close_dialog=False), only_errors=False)
        self.itemsChanged.emit()

    def _sync_bulk_summary(self) -> None:
        count = len(self._selected_keys)
        pending_visible = [
            self._record_key(row)
            for row in self._records
            if self._record_key(row) and bool(row.get("isBuiltin")) and not bool(row.get("isBuiltinAccepted"))
        ]
        pending_selected = [key for key in self._selected_keys if key in pending_visible]
        self.btn_accept_selected.setEnabled(bool(pending_selected or pending_visible))
        self.bulk_summary_label.setText(f"Seçili firma: {count}")
        self.btn_clear_selection.setEnabled(count > 0)
        self.btn_bulk_select_toggle.setSelectionCounts(count, len(self._records))

    def _sync_card_states(self) -> None:
        for record in self.list_widget.filtered_records or []:
            setattr(record, "_selected", self._record_key(record) in self._selected_keys)
        self.list_widget._build_page()
        active_record = next(
            (record for record in (self.list_widget.filtered_records or []) if self._record_key(record) == self._active_key),
            None,
        )
        if active_record is not None:
            self.list_widget.set_active_record(active_record)
        else:
            self.list_widget.clear_active_record()
        self._set_active_spin_enabled()
        self._update_pagination_ui()

    def _update_pagination_ui(self) -> None:
        total = len(self.list_widget.filtered_records or [])
        shown = self.list_widget.shown_count()
        self._workspace.set_records_summary_text(f"{shown} / {total} kayıt")
        self._workspace.footer_bar.refresh()
        self._sync_bulk_summary()

    def _on_card_selection_changed(self) -> None:
        self._selected_keys = {
            self._record_key(record)
            for record in self.list_widget.get_selected_records()
            if self._record_key(record)
        }
        self._sync_bulk_summary()
        self._update_pagination_ui()
        controller = getattr(self, "_workspace_controller", None)
        if controller is not None:
            controller.sync_state()

    def _clear_all_selections(self) -> None:
        self._selected_keys.clear()
        self._sync_bulk_summary()
        self._sync_card_states()
        if self._left_mode == "bulk":
            self._close_left_panel()

    def _set_list_loading(self, busy: bool, message: str = "Kargo firmaları yükleniyor...") -> None:
        self._workspace.set_list_loading(bool(busy), message=message)

    def _reload_context(self, *, active_key: str | None = None, preserve_page: bool = False) -> dict[str, object]:
        return {
            "active_key": _compact_text(active_key) or _compact_text(self._active_key),
            "current_page": self.list_widget.current_page if preserve_page else 1,
            "params": {
                "platform_code": self.platform_filter.currentData() or "",
                "search": self.search_input.text().strip(),
                "source_filter": self.source_filter.currentData() or "",
            },
        }

    def _apply_reload_result(self, result: Result, context: dict[str, object]) -> None:
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            return

        self._records = list((result.data or {}).get("records") or [])
        self._record_map = {_compact_text(row.get("key")): row for row in self._records}
        self._selected_keys = {key for key in self._selected_keys if key in self._record_map}
        user_count = sum(1 for row in self._records if not bool(row.get("isBuiltin")))
        self.filter_summary_label.setText(f"Toplam firma: {len(self._records)} | KullanÄ±cÄ±: {user_count}")
        self._workspace.set_filters_footer_text(self.filter_summary_label.text())

        card_records = [self._build_card_record(record) for record in self._records]
        self.list_widget.set_page_size(self._page_size)
        self.list_widget.set_records(card_records)
        self.list_widget.go_to_page(int(context.get("current_page") or 1))

        next_key = _compact_text(context.get("active_key")) or _compact_text(self._active_key)
        if next_key and next_key in self._record_map:
            self._active_key = next_key
            self._load_form(self._record_map[next_key], open_panel=False)
        elif self._left_mode == "edit":
            self._show_empty_edit_state()
        elif self._left_mode != "bulk":
            self._reset_form(open_panel=False)
        self._sync_card_states()

    def request_reload_items(self, *_args, active_key: str | None = None, preserve_page: bool = False) -> None:
        worker = self._reload_worker
        if worker is not None and worker.isRunning():
            self._reload_pending = True
            return
        self._reload_pending = False
        self._reload_seq += 1
        seq = int(self._reload_seq)
        context = self._reload_context(active_key=active_key, preserve_page=preserve_page)
        self._set_list_loading(True)
        worker = SyncWorker(load_logistics_cargo_providers, parent=self, **dict(context.get("params") or {}))
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

    def reload_items(self, *_args, active_key: str | None = None, preserve_page: bool = False) -> None:
        self._set_list_loading(True)
        try:
            result = load_logistics_cargo_providers(
                platform_code=self.platform_filter.currentData() or "",
                search=self.search_input.text().strip(),
                source_filter=self.source_filter.currentData() or "",
            )
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                return

            self._records = list((result.data or {}).get("records") or [])
            self._record_map = {_compact_text(row.get("key")): row for row in self._records}
            self._selected_keys = {key for key in self._selected_keys if key in self._record_map}
            user_count = sum(1 for row in self._records if not bool(row.get("isBuiltin")))
            self.filter_summary_label.setText(f"Toplam firma: {len(self._records)} | Kullanıcı: {user_count}")
            self._workspace.set_filters_footer_text(self.filter_summary_label.text())

            card_records = [self._build_card_record(record) for record in self._records]
            current_page = self.list_widget.current_page if preserve_page else 1
            self.list_widget.set_page_size(self._page_size)
            self.list_widget.set_records(card_records)
            self.list_widget.go_to_page(current_page)

            next_key = _compact_text(active_key) or _compact_text(self._active_key)
            if next_key and next_key in self._record_map:
                self._active_key = next_key
                self._load_form(self._record_map[next_key], open_panel=False)
            elif self._left_mode == "edit":
                self._show_empty_edit_state()
            elif self._left_mode != "bulk":
                self._reset_form(open_panel=False)
            self._sync_card_states()
        finally:
            self._set_list_loading(False)


__all__ = ["LogisticsCargoProvidersFormWindow"]
