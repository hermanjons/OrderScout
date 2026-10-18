from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QDialog, QPushButton, QLabel, QWidget,
    QVBoxLayout, QHBoxLayout, QSizePolicy, QPlainTextEdit,
    QFrame, QLineEdit, QListView, QFormLayout
)
from PyQt6.QtGui import QIcon, QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QModelIndex, QRect, QTimer

def _account_action(name: str):
    from Account.views import actions

    return getattr(actions, name)


def account_default_platform_label(*args, **kwargs):
    return _account_action("account_default_platform_label")(*args, **kwargs)


def account_visual_status(*args, **kwargs):
    return _account_action("account_visual_status")(*args, **kwargs)


def account_platform_options(*args, **kwargs):
    return _account_action("account_platform_options")(*args, **kwargs)


def collect_form_values(*args, **kwargs):
    return _account_action("collect_form_values")(*args, **kwargs)


def fill_company_form(*args, **kwargs):
    return _account_action("fill_company_form")(*args, **kwargs)


def handle_logo_selection(*args, **kwargs):
    return _account_action("handle_logo_selection")(*args, **kwargs)


def delete_company_and_refresh(*args, **kwargs):
    return _account_action("delete_company_and_refresh")(*args, **kwargs)


def get_platform_enabled_fields(*args, **kwargs):
    return _account_action("get_platform_enabled_fields")(*args, **kwargs)


def submit_company_values(*args, **kwargs):
    return _account_action("submit_company_values")(*args, **kwargs)


def account_platform_code(*args, **kwargs):
    from Account.constants.platform_constants import account_platform_code as _account_platform_code

    return _account_platform_code(*args, **kwargs)


def _account_platform_labels() -> dict[str, str]:
    from Account.constants import ACCOUNT_PLATFORM_LABELS

    return ACCOUNT_PLATFORM_LABELS


def get_all_companies(*args, **kwargs):
    from Account.processors.pipeline import get_all_companies as _get_all_companies

    return _get_all_companies(*args, **kwargs)


def run_company_api_health_check_batch(*args, **kwargs):
    from Account.processors.pipeline import run_company_api_health_check_batch as _run_company_api_health_check_batch

    return _run_company_api_health_check_batch(*args, **kwargs)


ACCOUNT_LOGO_ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
from Account.constants import (
    ACCOUNT_BULK_HEALTH_BUTTON_TEXT,
    ACCOUNT_BULK_HINT,
    ACCOUNT_BULK_OVERLAY_PROMPT,
    ACCOUNT_BULK_SUMMARY_TEMPLATE,
    ACCOUNT_BULK_TITLE,
    ACCOUNT_CARD_HOOK_HEIGHT,
    ACCOUNT_CARD_HOOK_WIDTH,
    ACCOUNT_CARD_ICON_SIZE,
    ACCOUNT_CARD_EXTRA_HEIGHT,
    ACCOUNT_CARD_EXTRA_TOP_GAP,
    ACCOUNT_CARD_META_FONT_SIZE,
    ACCOUNT_CARD_META_KEY_COLOR,
    ACCOUNT_CARD_META_VALUE_COLOR,
    ACCOUNT_CARD_ROW_HEIGHT,
    ACCOUNT_CARD_SELLER_ID_PREFIX,
    ACCOUNT_CARD_STATUS_PREFIX,
    ACCOUNT_CARD_TITLE_COLOR,
    ACCOUNT_CARD_TITLE_FALLBACK,
    ACCOUNT_CARD_TITLE_FONT_FAMILY,
    ACCOUNT_CARD_TITLE_FONT_SIZE,
    ACCOUNT_CARD_TITLE_HEIGHT,
    ACCOUNT_CARD_TITLE_TOP_OFFSET,
    ACCOUNT_CARD_SUBTITLE_HEIGHT,
    ACCOUNT_CARD_SUBTITLE_TOP_GAP,
    ACCOUNT_DELETE_CONFIRM_MESSAGE_TEMPLATE,
    ACCOUNT_DELETE_CONFIRM_TITLE,
    ACCOUNT_DELETE_NO_SELECTION_MESSAGE,
    ACCOUNT_DIALOG_MIN_SIZE,
    ACCOUNT_DIALOG_STYLESHEET,
    ACCOUNT_EDIT_CHOOSE_PROMPT,
    ACCOUNT_EDIT_OVERLAY_PROMPT,
    ACCOUNT_EDITOR_CLEAR_TEXT,
    ACCOUNT_EDITOR_DELETE_TEXT,
    ACCOUNT_FILTERS_SUBTITLE,
    ACCOUNT_FILTERS_SUMMARY_TEMPLATE,
    ACCOUNT_FILTERS_TITLE,
    ACCOUNT_FORM_FIELD_LABELS,
    ACCOUNT_FORM_FIELD_PLACEHOLDERS,
    ACCOUNT_FORM_SUBMIT_EDIT_TEXT,
    ACCOUNT_FORM_SUBMIT_NEW_TEXT,
    ACCOUNT_HEALTH_DONE_FALLBACK_TEXT,
    ACCOUNT_HEALTH_IDLE_TEXT,
    ACCOUNT_HEALTH_RUNNING_TEXT,
    ACCOUNT_LEFT_HINT_BULK,
    ACCOUNT_LEFT_HINT_EDIT_EMPTY,
    ACCOUNT_LEFT_HINT_EDIT_SELECTED_TEMPLATE,
    ACCOUNT_LEFT_HINT_NEW,
    ACCOUNT_LEFT_TITLE_BULK,
    ACCOUNT_LEFT_TITLE_EDIT,
    ACCOUNT_LEFT_TITLE_NEW,
    ACCOUNT_LIST_LOADING_TEXT,
    ACCOUNT_LIST_EMPTY_TEXT,
    ACCOUNT_LOGO_BUTTON_TEXT,
    ACCOUNT_LOGO_CLEAR_TEXT,
    ACCOUNT_LOGO_DIALOG_FILTER,
    ACCOUNT_LOGO_DIALOG_TITLE,
    ACCOUNT_RECORDS_TITLE,
    ACCOUNT_RECORDS_INITIAL_SUMMARY,
    ACCOUNT_RECORDS_SUMMARY_TEMPLATE,
    ACCOUNT_SESSION_HEALTH_FAILED_TEMPLATE,
    ACCOUNT_SIDEBAR_BULK_TOOLTIP,
    ACCOUNT_SIDEBAR_EDIT_TOOLTIP,
    ACCOUNT_SIDEBAR_NEW_TOOLTIP,
    ACCOUNT_SUBMIT_RUNNING_TEXT,
    ACCOUNT_BULK_HEALTH_FAILED_TEMPLATE,
    ACCOUNT_BULK_NO_SELECTION_MESSAGE,
    ACCOUNT_WINDOW_TITLE,
    ACCOUNT_WORKSPACE_PAGE_SIZE_OPTIONS,
    ACCOUNT_WORKSPACE_SHELL_KWARGS,
)
from Account.constants.paths import (
    ACCOUNT_SIDEBAR_BULK_ICON_PATH,
    ACCOUNT_SIDEBAR_EDIT_ICON_PATH,
    ACCOUNT_SIDEBAR_NEW_ICON_PATH,
    ACCOUNT_TOOLBAR_ICON_PATH,
)
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from Account.constants import ui_text
from Core.views import (
    SwitchButton,
    SwitchSelectWidget,
    FileBadgePicker,
    AppMessageCenter,
    compose_record_workspace_style,
    RecordWorkspaceBehaviorAdapter,
    RecordWorkspaceCardRecord,
    RecordWorkspaceListDelegate,
    RecordWorkspaceListModel,
    RecordWorkspaceListWidget,
    RecordWorkspaceScaffold,
)
from Core.threads.sync_worker import SyncWorker

from Account.signals.signals import account_signals
@dataclass
class CompanyWorkspaceRecord(RecordWorkspaceCardRecord):
    @classmethod
    def from_account(cls, account) -> "CompanyWorkspaceRecord":
        pk = getattr(account, "pk", None)
        seller_id = str(getattr(account, "account_id", "") or "").strip()
        platform_code = account_platform_code(getattr(account, "platform", "") or "")
        platform = str(_account_platform_labels().get(platform_code) or "")
        status = account_visual_status(account)
        subtitle_parts = [
            part for part in (platform, f"{ACCOUNT_CARD_SELLER_ID_PREFIX}: {seller_id}" if seller_id else "") if part
        ]
        return cls(
            orderNumber=str(pk if pk is not None else seller_id or getattr(account, "comp_name", "") or ""),
            title=str(getattr(account, "comp_name", "") or "").strip() or ACCOUNT_CARD_TITLE_FALLBACK,
            subtitle=" | ".join(subtitle_parts),
            extra=f"{ACCOUNT_CARD_STATUS_PREFIX}: {status}",
            logo_path=str(getattr(account, "logo_path", None) or ""),
            payload=account,
        )


class CompanyManagerRecordListDelegate(RecordWorkspaceListDelegate):
    def __init__(self, parent=None, *, on_select_button=None):
        super().__init__(parent, on_select_button=on_select_button)
        self._icon_size = ACCOUNT_CARD_ICON_SIZE
        self._row_height = ACCOUNT_CARD_ROW_HEIGHT
        self._hook_w = ACCOUNT_CARD_HOOK_WIDTH
        self._hook_h = ACCOUNT_CARD_HOOK_HEIGHT

    def _paint_card_content(self, painter: QPainter, rect: QRect, index: QModelIndex, hook_rect: QRect) -> None:
        title = index.data(RecordWorkspaceListModel.TitleRole) or ""
        subtitle = index.data(RecordWorkspaceListModel.SubtitleRole) or ""
        extra = index.data(RecordWorkspaceListModel.ExtraRole) or ""

        icon_rect = self._icon_rect(rect)
        self._paint_card_icon(painter, index, icon_rect)

        x = self._content_left(rect)
        text_width = self._text_width(rect, hook_rect)

        painter.setPen(QColor(ACCOUNT_CARD_TITLE_COLOR))
        painter.setFont(QFont(ACCOUNT_CARD_TITLE_FONT_FAMILY, ACCOUNT_CARD_TITLE_FONT_SIZE, QFont.Weight.Bold))
        title_rect = QRect(x, rect.top() + ACCOUNT_CARD_TITLE_TOP_OFFSET, text_width, ACCOUNT_CARD_TITLE_HEIGHT)
        fm = painter.fontMetrics()
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(title, Qt.TextElideMode.ElideRight, title_rect.width()),
        )

        subtitle_rect = QRect(
            x,
            title_rect.bottom() + ACCOUNT_CARD_SUBTITLE_TOP_GAP,
            text_width,
            ACCOUNT_CARD_SUBTITLE_HEIGHT,
        )
        self._draw_labeled_segments_line(
            painter,
            subtitle_rect,
            subtitle,
            key_color=QColor(ACCOUNT_CARD_META_KEY_COLOR),
            value_color=QColor(ACCOUNT_CARD_META_VALUE_COLOR),
            point_size=ACCOUNT_CARD_META_FONT_SIZE,
        )

        extra_rect = QRect(
            x,
            subtitle_rect.bottom() + ACCOUNT_CARD_EXTRA_TOP_GAP,
            text_width,
            ACCOUNT_CARD_EXTRA_HEIGHT,
        )
        self._draw_labeled_single_line(
            painter,
            extra_rect,
            extra,
            key_color=QColor(ACCOUNT_CARD_META_KEY_COLOR),
            value_color=QColor(ACCOUNT_CARD_META_VALUE_COLOR),
            point_size=ACCOUNT_CARD_META_FONT_SIZE,
        )


class CompanyManagerRecordListWidget(RecordWorkspaceListWidget):
    def __init__(self, parent=None):
        super().__init__(
            parent,
            empty_placeholder_text=str(ui_text("account.list.empty", ACCOUNT_LIST_EMPTY_TEXT)),
        )
        self._delegate = CompanyManagerRecordListDelegate(self, on_select_button=self._on_select_button_clicked)
        self._row_by_account_pk: dict[int, int] = {}
        self._row_by_record_key: dict[str, int] = {}
        self.setItemDelegate(self._delegate)
        self.set_page_size(int(ACCOUNT_WORKSPACE_PAGE_SIZE_OPTIONS[0]))

    @staticmethod
    def _normalized_account_pk(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def set_companies(self, records: list) -> None:
        company_records: list[CompanyWorkspaceRecord] = []
        row_by_account_pk: dict[int, int] = {}
        row_by_record_key: dict[str, int] = {}
        for row, account in enumerate(records or []):
            record = CompanyWorkspaceRecord.from_account(account)
            company_records.append(record)
            account_pk = self._normalized_account_pk(getattr(account, "pk", None))
            if account_pk is not None:
                row_by_account_pk[account_pk] = row
            record_key = str(getattr(record, "recordKey", "") or "").strip().upper()
            if record_key:
                row_by_record_key[record_key] = row
        self._row_by_account_pk = row_by_account_pk
        self._row_by_record_key = row_by_record_key
        self.set_records(company_records)
        self.clear_active_record()

    def rowCount(self) -> int:
        return len(self.records or [])

    def account_at(self, row: int):
        if 0 <= row < len(self.records or []):
            return getattr(self.records[row], "payload", None)
        return None

    def set_selected_row(self, row: int | None) -> None:
        if row is None or row < 0 or row >= len(self.records or []):
            self.clear_active_record()
            return
        self.set_active_record(self.records[row])

    def selected_row(self) -> int | None:
        active_key = str(getattr(self, "_active_record_key", "") or "").strip().upper()
        if not active_key:
            return None
        return self._row_by_record_key.get(active_key)

    def row_for_account_pk(self, account_pk: object) -> int | None:
        normalized_pk = self._normalized_account_pk(account_pk)
        if normalized_pk is None:
            return None
        return self._row_by_account_pk.get(normalized_pk)

    def set_bulk_selected_row(self, row: int, selected: bool) -> bool:
        if row < 0 or row >= len(self.records or []):
            return False
        record = self.records[row]
        self.set_record_selected(record, bool(selected))
        return bool(getattr(record, "_selected", False))

    def toggle_bulk_selected_row(self, row: int) -> bool:
        if row < 0 or row >= len(self.records or []):
            return False
        record = self.records[row]
        selected = not bool(getattr(record, "_selected", False))
        self.set_record_selected(record, selected)
        return selected

    def clear_bulk_selected_rows(self) -> None:
        for record in list(self.get_selected_records()):
            self.set_record_selected(record, False)

    def bulk_selected_accounts(self) -> list:
        return [
            getattr(record, "payload", None)
            for record in self.get_selected_records()
            if getattr(record, "payload", None) is not None
        ]

    def bulk_selected_count(self) -> int:
        return len(self.get_selected_records())


class AccountWorkspaceBehaviorAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, dialog: "CompanyManagerDialog") -> None:
        self.dialog = dialog
        self.new_panel_id = "new"
        self.edit_panel_id = "edit"
        self.bulk_panel_id = "bulk"
        self.clear_active_on_close = True

    @property
    def list_widget(self):
        return self.dialog.list_view

    def get_mode(self) -> str:
        return str(getattr(self.dialog, "_left_mode", "edit") or "edit")

    def set_mode(self, mode: str) -> None:
        self.dialog._set_left_mode(mode)

    def get_active_key(self) -> str:
        return str(getattr(getattr(self.dialog, "account", None), "pk", None) or "")

    def get_selected_count(self) -> int:
        return int(self.dialog.list_model.bulk_selected_count() or 0)

    def get_record_key(self, record) -> str:
        return str(getattr(getattr(record, "payload", None), "pk", "") or "")

    def prepare_new(self) -> None:
        self.dialog._workspace_prepare_new_form()

    def edit_without_active(self) -> None:
        self.dialog._workspace_prepare_empty_edit()

    def activate_record(self, record) -> None:
        self.dialog._workspace_activate_account_record(record)

    def clear_active(self) -> None:
        self.dialog._clear_active_edit_selection()

    def apply_selection(self, record, selected: bool) -> None:
        self.dialog._workspace_apply_selection(record, selected)

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self.dialog._set_select_button_guide_enabled(enabled)

    def on_state_changed(self) -> None:
        self.dialog._on_workspace_state_changed()

    def open_panel(self, shell) -> None:
        _ = shell
        self.dialog._open_editor_panel()

    def close_panel(self, shell) -> None:
        shell.close_left_panel()

    def edit_guidance_message(self) -> str:
        return str(ui_text("account.edit.overlay_prompt", ACCOUNT_EDIT_OVERLAY_PROMPT))

    def bulk_guidance_message(self) -> str:
        return str(ui_text("account.bulk.overlay_prompt", ACCOUNT_BULK_OVERLAY_PROMPT))


class CompanyManagerDialog(QDialog):
    _session_health_check_done = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(ACCOUNT_WINDOW_TITLE)
        self.setMinimumSize(*ACCOUNT_DIALOG_MIN_SIZE)
        flags = self.windowFlags()
        flags |= Qt.WindowType.WindowMinMaxButtonsHint
        flags |= Qt.WindowType.WindowCloseButtonHint
        flags &= ~Qt.WindowType.WindowContextHelpButtonHint
        self.setWindowFlags(flags)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        self._left_mode = "edit"
        self._health_worker: SyncWorker | None = None
        self._reload_worker: SyncWorker | None = None
        self._submit_worker: SyncWorker | None = None
        self._reload_seq = 0
        self._records_cache: list = []
        self._card_spin_enabled = False

        self.setObjectName("CompanyDialogRoot")
        self.setStyleSheet(compose_record_workspace_style(ACCOUNT_DIALOG_STYLESHEET))

        self.setWindowIcon(QIcon(str(ACCOUNT_TOOLBAR_ICON_PATH)))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(10)

        # Records Scaffold

        self._workspace = RecordWorkspaceScaffold(
            self,
            left_title=str(ui_text("account.left.title_edit", ACCOUNT_LEFT_TITLE_EDIT)),
            left_subtitle=str(ui_text("account.left.hint_edit_empty", ACCOUNT_LEFT_HINT_EDIT_EMPTY)),
            filters_title=str(ui_text("account.filters.title", ACCOUNT_FILTERS_TITLE)),
            filters_subtitle=str(ui_text("account.filters.subtitle", ACCOUNT_FILTERS_SUBTITLE)),
            records_title=str(ui_text("account.records.title", ACCOUNT_RECORDS_TITLE)),
            shell_kwargs=ACCOUNT_WORKSPACE_SHELL_KWARGS,
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": str(ui_text("account.sidebar.new_tooltip", ACCOUNT_SIDEBAR_NEW_TOOLTIP)),
                    "icon_path": str(ACCOUNT_SIDEBAR_NEW_ICON_PATH),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": str(ui_text("account.sidebar.editor_tooltip", ACCOUNT_SIDEBAR_EDIT_TOOLTIP)),
                    "icon_path": str(ACCOUNT_SIDEBAR_EDIT_ICON_PATH),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "bulk",
                    "text": "",
                    "tooltip": str(ui_text("account.sidebar.bulk_tooltip", ACCOUNT_SIDEBAR_BULK_TOOLTIP)),
                    "icon_path": str(ACCOUNT_SIDEBAR_BULK_ICON_PATH),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
            ),
            page_size_options=ACCOUNT_WORKSPACE_PAGE_SIZE_OPTIONS,
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
        )
        main_layout.addWidget(self._workspace, 1)

        self._workspace_shell = self._workspace.shell
        self._panel_sidebar = self._workspace.sidebar
        self._company_splitter = self._workspace_shell.splitter
        self._left_card = self._workspace.left_card
        self.left_panel_title = self._workspace.left_card.title_label
        self.left_panel_hint = self._workspace.left_card.subtitle_label
        self.left_panel_hint.setObjectName("FieldLabel")
        self._editor_scroll = self._workspace.editor_scroll
        self._editor_actions_wrap = self._workspace.editor_actions_host
        self.bulk_panel = self._workspace.bulk_panel
        self._initial_panel_state_applied = False

        form_host = QWidget(self._workspace.editor_host)
        form_host.setStyleSheet("background: transparent;")
        form = QFormLayout(form_host)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(14)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        def form_label(text: str) -> QLabel:
            label = QLabel(text, form_host)
            label.setObjectName("FieldLabel")
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return label

        self._account_form_rows: dict[str, tuple[QLabel, QWidget]] = {}

        def add_form_row(name: str, text: str, widget: QWidget, alignment: Qt.AlignmentFlag | None = None) -> None:
            label = form_label(text)
            if alignment is not None:
                form.addRow(label, widget)
                form.labelForField(widget).setAlignment(alignment)
            else:
                form.addRow(label, widget)
            self._account_form_rows[name] = (label, widget)

        self.account = None
        self.logo_path: str | None = None
        self._pending_select_pk: int | None = None

        self.seller_id_input = QLineEdit(form_host)
        self.comp_name_input = QLineEdit(form_host)
        self.api_key_input = QLineEdit(form_host)
        self.api_secret_input = QLineEdit(form_host)
        self.integration_code_input = QLineEdit(form_host)
        self.token_input = QLineEdit(form_host)

        self.seller_id_input.setPlaceholderText(ACCOUNT_FORM_FIELD_PLACEHOLDERS["account_id"])
        self.comp_name_input.setPlaceholderText(ACCOUNT_FORM_FIELD_PLACEHOLDERS["comp_name"])
        self.api_key_input.setPlaceholderText(ACCOUNT_FORM_FIELD_PLACEHOLDERS["api_key"])
        self.api_secret_input.setPlaceholderText(ACCOUNT_FORM_FIELD_PLACEHOLDERS["api_secret"])
        self.integration_code_input.setPlaceholderText(ACCOUNT_FORM_FIELD_PLACEHOLDERS["integration_code"])
        self.token_input.setPlaceholderText(ACCOUNT_FORM_FIELD_PLACEHOLDERS["token"])

        self.platform_input = SwitchSelectWidget(form_host, multi=False, include_all=False, search_enabled=False)
        self.platform_input.setObjectName("PlatformSelect")
        self.platform_input.addItems(account_platform_options())
        if account_default_platform_label():
            self.platform_input.setCurrentText(account_default_platform_label())
        else:
            self.platform_input.setCurrentText("")
        self.platform_input.setMinimumHeight(46)
        self.platform_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.extra_config_input = QPlainTextEdit(form_host)
        self.extra_config_input.setPlaceholderText(ACCOUNT_FORM_FIELD_PLACEHOLDERS["extra_config"])
        self.extra_config_input.setFixedHeight(120)

        for w in (
            self.seller_id_input,
            self.comp_name_input,
            self.api_key_input,
            self.api_secret_input,
            self.integration_code_input,
            self.token_input,
        ):
            w.setMinimumHeight(34)

        add_form_row("account_id", ACCOUNT_FORM_FIELD_LABELS["account_id"], self.seller_id_input)
        add_form_row("platform", ACCOUNT_FORM_FIELD_LABELS["platform"], self.platform_input)
        add_form_row("comp_name", ACCOUNT_FORM_FIELD_LABELS["comp_name"], self.comp_name_input)
        add_form_row("api_key", ACCOUNT_FORM_FIELD_LABELS["api_key"], self.api_key_input)
        add_form_row("api_secret", ACCOUNT_FORM_FIELD_LABELS["api_secret"], self.api_secret_input)
        add_form_row("integration_code", ACCOUNT_FORM_FIELD_LABELS["integration_code"], self.integration_code_input)
        add_form_row("token", ACCOUNT_FORM_FIELD_LABELS["token"], self.token_input)
        add_form_row(
            "extra_config",
            ACCOUNT_FORM_FIELD_LABELS["extra_config"],
            self.extra_config_input,
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        logo_wrap = QWidget(form_host)
        logo_wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.logo_selector = FileBadgePicker(
            logo_wrap,
            button_text=ACCOUNT_LOGO_BUTTON_TEXT,
            clear_text=ACCOUNT_LOGO_CLEAR_TEXT,
            dialog_title=ACCOUNT_LOGO_DIALOG_TITLE,
            dialog_filter=ACCOUNT_LOGO_DIALOG_FILTER,
            allow_multiple=False,
            allowed_extensions=list(ACCOUNT_LOGO_ALLOWED_EXTENSIONS),
        )
        self.logo_selector.filesChanged.connect(self._on_logo_files_changed)

        logo_col = QVBoxLayout(logo_wrap)
        logo_col.setContentsMargins(0, 0, 0, 0)
        logo_col.setSpacing(8)
        logo_col.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        logo_col.addWidget(self.logo_selector)
        add_form_row("logo", ACCOUNT_FORM_FIELD_LABELS["logo"], logo_wrap)

        status_wrap = QWidget(form_host)
        status_wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        status_layout = QHBoxLayout(status_wrap)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(10)
        status_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.is_active_input = SwitchButton(status_wrap)
        self.is_active_input.setChecked(True)
        status_layout.addWidget(self.is_active_input)
        status_layout.addStretch()
        add_form_row("is_active", ACCOUNT_FORM_FIELD_LABELS["is_active"], status_wrap)

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text=ACCOUNT_EDITOR_CLEAR_TEXT,
            save_new_text=str(ui_text("account.form.submit_new", ACCOUNT_FORM_SUBMIT_NEW_TEXT)),
            save_edit_text=str(ui_text("account.form.submit_edit", ACCOUNT_FORM_SUBMIT_EDIT_TEXT)),
            delete_text=ACCOUNT_EDITOR_DELETE_TEXT,
        )
        self.btn_new = self._workspace.editor_action_bar.clear_button
        self.btn_save = self._workspace.editor_action_bar.save_button
        self.btn_delete = self._workspace.editor_action_bar.delete_button
        self.btn_delete.setEnabled(False)
        self._workspace.editor_action_bar.clearRequested.connect(self._open_new_form)
        self._workspace.editor_action_bar.saveRequested.connect(self.on_submit)
        self._workspace.editor_action_bar.deleteRequested.connect(self.delete_company)
        bulk_content = QWidget(self.bulk_panel)
        bulk_layout = QVBoxLayout(bulk_content)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.setSpacing(8)

        self.bulk_summary = QLabel(bulk_content) # Tanımı koruyoruz ama layout'a eklemiyoruz
        self.btn_bulk_health = QPushButton(
            str(ui_text("account.bulk.health_button", ACCOUNT_BULK_HEALTH_BUTTON_TEXT)),
            bulk_content,
        )
        self.btn_bulk_health.setObjectName("PrimaryButton")
        self.btn_bulk_health.setMinimumHeight(34)
        self.btn_bulk_health.setEnabled(False)
        self.btn_bulk_health.clicked.connect(self._run_bulk_health_check)
        
        # Sadece buton kalsın istendiği için diğer metinler layout'a eklenmiyor
        bulk_layout.addWidget(self.btn_bulk_health)
        bulk_layout.addStretch(1)

        self._workspace.set_editor_widget(form_host)
        self._workspace.set_bulk_widget(bulk_content)

        filters_host = QWidget(self._workspace.filters_host)
        filters_layout = QVBoxLayout(filters_host)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(6)
        self.health_status_label = QLabel(
            str(ui_text("account.health.idle", ACCOUNT_HEALTH_IDLE_TEXT)),
            filters_host,
        )
        self.health_status_label.setObjectName("FieldLabel")
        self.health_status_label.setWordWrap(True)
        self.company_total_label = QLabel(
            str(ui_text("account.filters.summary", ACCOUNT_FILTERS_SUMMARY_TEMPLATE)).format(total=0, selected=0),
            filters_host,
        )
        self.company_total_label.setObjectName("Muted")
        self.company_total_label.setWordWrap(True)
        filters_layout.addWidget(self.health_status_label)
        filters_layout.addWidget(self.company_total_label)
        filters_layout.addStretch(1)
        self._workspace.set_filters_widget(filters_host)

        self.list_view = CompanyManagerRecordListWidget(self._workspace.records_card)
        self.list_model = self.list_view
        self._workspace.set_list_widget(self.list_view)
        self.list_view.page_changed.connect(lambda *_args: self._sync_workspace_summary())
        self.list_view.selection_changed.connect(self._update_bulk_panel_state)
        self._workspace.set_records_summary_text(ACCOUNT_RECORDS_INITIAL_SUMMARY)
        self._company_splitter.setSizes([520, 980])

        self._workspace_adapter = AccountWorkspaceBehaviorAdapter(self)
        self._workspace_controller = self._workspace.create_behavior_controller(
            adapter=self._workspace_adapter,
        )

        self.platform_input.currentIndexChanged.connect(lambda _i: self.apply_platform_rules(self.platform_input.currentText()))
        self.apply_platform_rules(self.platform_input.currentText())

        account_signals.company_changed.connect(self._reload_list)
        self._set_left_mode("edit")
        self._reload_list()
        QTimer.singleShot(0, self._run_session_health_check_once)

    def _track_worker(self, attr_name: str, worker: SyncWorker) -> SyncWorker:
        setattr(self, attr_name, worker)

        def _release() -> None:
            if getattr(self, attr_name, None) is worker:
                setattr(self, attr_name, None)
            worker.deleteLater()

        worker.finished.connect(_release)
        return worker

    def _detach_worker(self, attr_name: str) -> None:
        worker = getattr(self, attr_name, None)
        if worker is None:
            return
        try:
            worker.result_ready.disconnect()
        except Exception:
            pass
        try:
            worker.finished.disconnect()
        except Exception:
            pass
        try:
            if worker.parent() is self:
                worker.setParent(None)
        except Exception:
            pass
        try:
            if worker.isRunning():
                worker.finished.connect(worker.deleteLater)
            else:
                worker.deleteLater()
        except Exception:
            pass
        setattr(self, attr_name, None)

    def closeEvent(self, event) -> None:
        self._detach_worker("_reload_worker")
        self._detach_worker("_health_worker")
        self._detach_worker("_submit_worker")
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_company_list_layout()
        self._sync_guidance_overlays_geometry()
        self._update_edit_lock_state()
        self._sync_card_spin_state()

    def _refresh_company_list_layout(self):
        try:
            self.list_view.doItemsLayout()
            self.list_view.viewport().update()
        except Exception:
            return

    def _is_editor_panel_open(self) -> bool:
        return bool(self._workspace_shell.is_left_panel_open())

    def _sync_sidebar_state_from_splitter(self):
        self._workspace_controller.sync_state()

    def _sync_guidance_overlays_geometry(self):
        self._workspace_shell.sync_guidance_geometry()
        self._workspace.sync_list_loading_geometry()

    def _set_list_loading(self, busy: bool, message: str = ACCOUNT_LIST_LOADING_TEXT) -> None:
        self._workspace.set_list_loading(bool(busy), message=message)

    def _sync_workspace_summary(self) -> None:
        total = len(self._records_cache)
        selected = self.list_model.bulk_selected_count()
        self._workspace.set_records_summary_text(
            ACCOUNT_RECORDS_SUMMARY_TEMPLATE.format(shown=min(total, self.list_view.shown_count()), total=total)
        )
        self.company_total_label.setText(
            str(ui_text("account.filters.summary", ACCOUNT_FILTERS_SUMMARY_TEMPLATE)).format(
                total=total,
                selected=selected,
            )
        )

    @staticmethod
    def _health_payload_for_account(account) -> dict[str, object]:
        return {
            "pk": getattr(account, "pk", None),
            "comp_name": getattr(account, "comp_name", ""),
            "platform": getattr(account, "platform", ""),
            "account_id": getattr(account, "account_id", ""),
            "api_key": getattr(account, "api_key", ""),
            "api_secret": getattr(account, "api_secret", ""),
            "integration_code": getattr(account, "integration_code", ""),
            "token": getattr(account, "token", ""),
            "extra_config": getattr(account, "extra_config", None),
        }

    def _workspace_prepare_new_form(self) -> None:
        self.clear_form(mode=None)
        self._set_left_mode("new")

    def _workspace_prepare_empty_edit(self) -> None:
        self.clear_form(mode=None)
        self._set_left_mode("edit")
        self.health_status_label.setText(str(ui_text("account.edit.choose_prompt", ACCOUNT_EDIT_CHOOSE_PROMPT)))

    def _workspace_activate_account_record(self, record) -> None:
        clicked_pk = getattr(getattr(record, "payload", None), "pk", None)
        row = self.list_model.row_for_account_pk(clicked_pk)
        if row is None:
            return
        self._activate_row_for_edit(row, allow_toggle=False)

    def _workspace_apply_selection(self, record, selected: bool) -> None:
        clicked_pk = getattr(getattr(record, "payload", None), "pk", None)
        row = self.list_model.row_for_account_pk(clicked_pk)
        if row is None:
            return
        self.list_model.set_bulk_selected_row(row, bool(selected))
        self._update_bulk_panel_state()

    def _on_workspace_state_changed(self) -> None:
        self._sync_guidance_overlays_geometry()
        self._update_edit_lock_state()
        self._sync_card_spin_state()
        self._update_bulk_panel_state()

    def _set_card_spin_enabled(self, enabled: bool):
        self._card_spin_enabled = bool(enabled)
        self.list_view.set_active_spin_allowed(self._card_spin_enabled)

    def _set_select_button_guide_enabled(self, enabled: bool):
        self.list_view.set_select_button_guide_enabled(bool(enabled))

    def _sync_card_spin_state(self):
        selected_row = self.list_model.selected_row()
        enabled = (
            selected_row is not None
            and self._left_mode == "edit"
            and self.account is not None
            and self._is_editor_panel_open()
        )
        self._set_card_spin_enabled(bool(enabled))

    def _set_editor_inputs_enabled(self, enabled: bool):
        widgets = [
            self.seller_id_input,
            self.comp_name_input,
            self.api_key_input,
            self.api_secret_input,
            self.integration_code_input,
            self.token_input,
            self.extra_config_input,
            self.platform_input,
            self.is_active_input,
            self.logo_selector,
            self.btn_new,
            self.btn_save,
            self.btn_delete,
        ]
        for widget in widgets:
            try:
                widget.setEnabled(enabled)
            except Exception:
                pass

    def _set_submit_busy(self, busy: bool) -> None:
        enabled = not bool(busy)
        self._set_editor_inputs_enabled(enabled)
        self._sync_form_submit_button()
        if busy:
            self.btn_save.setEnabled(False)
            self.btn_new.setEnabled(False)
            self.btn_delete.setEnabled(False)

    def _update_edit_lock_state(self):
        panel_open = self._is_editor_panel_open()
        lock_edit = self._left_mode == "edit" and self.account is None and panel_open
        lock_bulk = self._left_mode == "bulk" and self.list_model.bulk_selected_count() <= 0 and panel_open
        self._edit_lock_active = bool(lock_edit)
        self._bulk_lock_active = bool(lock_bulk)

        if lock_edit or lock_bulk:
            if lock_edit:
                self._set_editor_inputs_enabled(False)
            else:
                self._set_editor_inputs_enabled(True)
            return

        self._set_editor_inputs_enabled(True)
        self.apply_platform_rules(self.platform_input.currentText())
        if self.account is None:
            self.btn_delete.setEnabled(False)

    def _open_editor_panel(self):
        self._workspace_shell.open_left_panel(left_width=520, min_left=320, min_right=220)
        self._sync_sidebar_state_from_splitter()

    def _clear_active_edit_selection(self):
        self.account = None
        self.list_model.set_selected_row(None)
        self.btn_delete.setEnabled(False)
        self._refresh_left_panel_header()
        self._sync_card_spin_state()

    def _close_editor_panel(self):
        self._clear_active_edit_selection()
        self._workspace_shell.close_left_panel()
        self._sync_sidebar_state_from_splitter()

    def _refresh_left_panel_header(self):
        mode = self._left_mode
        self._sync_form_submit_button()
        if mode == "new":
            self.left_panel_title.setText(str(ui_text("account.left.title_new", ACCOUNT_LEFT_TITLE_NEW)))
            self.left_panel_hint.setText(str(ui_text("account.left.hint_new", ACCOUNT_LEFT_HINT_NEW)))
            return
        if mode == "bulk":
            self.left_panel_title.setText(str(ui_text("account.left.title_bulk", ACCOUNT_LEFT_TITLE_BULK)))
            self.left_panel_hint.setText(str(ui_text("account.left.hint_bulk", ACCOUNT_LEFT_HINT_BULK)))
            return

        self.left_panel_title.setText(str(ui_text("account.left.title_edit", ACCOUNT_LEFT_TITLE_EDIT)))
        if self.account is None:
            self.left_panel_hint.setText(str(ui_text("account.left.hint_edit_empty", ACCOUNT_LEFT_HINT_EDIT_EMPTY)))
            return
        name = str(getattr(self.account, "comp_name", "") or "").strip() or "-"
        self.left_panel_hint.setText(
            str(ui_text("account.left.hint_edit_selected", ACCOUNT_LEFT_HINT_EDIT_SELECTED_TEMPLATE)).format(name=name)
        )

    def _sync_form_submit_button(self):
        mode = str(getattr(self, "_left_mode", "edit") or "edit").lower()
        if mode == "new":
            self.btn_save.setEnabled(True)
            return
        if mode == "edit":
            self.btn_save.setEnabled(self.account is not None)
            return
        self.btn_save.setEnabled(False)

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

    def _open_new_form(self, _checked: bool = False):
        self._workspace_controller.handle_panel_sidebar_toggled("new", True)

    def _update_bulk_panel_state(self):
        count = self.list_model.bulk_selected_count()
        self.bulk_summary.setText(str(ui_text("account.bulk.summary", ACCOUNT_BULK_SUMMARY_TEMPLATE)).format(count=count))
        self.btn_bulk_health.setEnabled(count > 0)
        self._sync_workspace_summary()

    def _selected_bulk_accounts_payload(self) -> list[dict]:
        payload: list[dict] = []
        for acc in self.list_model.bulk_selected_accounts():
            payload.append(self._health_payload_for_account(acc))
        return payload

    def _run_bulk_health_check(self):
        payload = self._selected_bulk_accounts_payload()
        if not payload:
            MessageHandler.show(
                self,
                Result.fail(ACCOUNT_BULK_NO_SELECTION_MESSAGE, close_dialog=False),
                only_errors=True,
            )
            return
        self.btn_bulk_health.setEnabled(False)
        self.health_status_label.setText(str(ui_text("account.health.running", ACCOUNT_HEALTH_RUNNING_TEXT)))
        self._health_worker = self._track_worker(
            "_health_worker",
            SyncWorker(run_company_api_health_check_batch, payload, parent=self),
        )
        self._health_worker.result_ready.connect(self._on_bulk_health_result)
        self._health_worker.finished.connect(lambda: self.btn_bulk_health.setEnabled(self.list_model.bulk_selected_count() > 0))
        self._health_worker.start()

    def _on_bulk_health_result(self, result: Result):
        self.health_status_label.setText(str(result.message or ACCOUNT_HEALTH_DONE_FALLBACK_TEXT))
        data = result.data or {}
        failed = int(data.get("failed") or 0)
        if failed > 0:
            MessageHandler.show(
                self,
                Result.fail(
                    ACCOUNT_BULK_HEALTH_FAILED_TEMPLATE.format(failed=failed),
                    close_dialog=False,
                    data=data,
                ),
                only_errors=True,
            )

    def _run_session_health_check_once(self):
        if CompanyManagerDialog._session_health_check_done:
            return
        if not self._records_cache:
            return

        payload = [self._health_payload_for_account(acc) for acc in self._records_cache]
        if not payload:
            return

        CompanyManagerDialog._session_health_check_done = True
        self.health_status_label.setText(str(ui_text("account.health.running", ACCOUNT_HEALTH_RUNNING_TEXT)))
        self._health_worker = self._track_worker(
            "_health_worker",
            SyncWorker(run_company_api_health_check_batch, payload, parent=self),
        )
        self._health_worker.result_ready.connect(self._on_session_health_result)
        self._health_worker.start()

    def _on_session_health_result(self, result: Result):
        self.health_status_label.setText(str(result.message or ACCOUNT_HEALTH_DONE_FALLBACK_TEXT))
        data = result.data or {}
        failed = int(data.get("failed") or 0)
        if failed > 0:
            MessageHandler.show(
                self,
                Result.fail(
                    ACCOUNT_SESSION_HEALTH_FAILED_TEMPLATE.format(failed=failed),
                    close_dialog=False,
                    data=data,
                ),
                only_errors=True,
            )

    def _reload_list(self):
        self._reload_seq += 1
        seq = int(self._reload_seq)
        self._set_list_loading(True, ACCOUNT_LIST_LOADING_TEXT)

        worker = SyncWorker(get_all_companies, parent=self)
        self._reload_worker = self._track_worker("_reload_worker", worker)

        def _after(result: Result):
            if seq != self._reload_seq:
                return
            try:
                if not result.success:
                    MessageHandler.show(self, result, only_errors=True)
                    return
                records = result.data.get("records", []) or []
                current_edit_pk = getattr(self.account, "pk", None) if self._left_mode == "edit" else None
                self._records_cache = records
                self.list_model.set_companies(records)
                found_pending = False
                restored_active = False
                if self._pending_select_pk is not None:
                    found_pending = self._restore_account_selection(self._pending_select_pk)
                    self._pending_select_pk = None
                if not found_pending and current_edit_pk is not None:
                    restored_active = self._restore_account_selection(current_edit_pk)

                if not records:
                    self._close_editor_panel()
                elif not self._initial_panel_state_applied and not found_pending:
                    self._close_editor_panel()
                elif current_edit_pk is not None and not restored_active and not found_pending:
                    self._close_editor_panel()

                self._update_bulk_panel_state()
                self._sync_workspace_summary()
                if self._left_mode == "bulk" and self._is_editor_panel_open() and self.list_model.bulk_selected_count() <= 0:
                    self._close_editor_panel()
                if records and not CompanyManagerDialog._session_health_check_done:
                    QTimer.singleShot(0, self._run_session_health_check_once)
                self._initial_panel_state_applied = True
                self._sync_card_spin_state()
            except Exception as e:
                MessageHandler.show(self, Result.fail(map_error_to_message(e), error=e), only_errors=True)
            finally:
                self._set_list_loading(False)

        def _on_finished():
            if seq == self._reload_seq:
                self._set_list_loading(False)

        worker.result_ready.connect(_after)
        worker.finished.connect(_on_finished)
        worker.start()

    def _restore_account_selection(self, account_pk: int | None) -> bool:
        row = self.list_model.row_for_account_pk(account_pk)
        if row is None:
            return False
        self._activate_row_for_edit(row, allow_toggle=False)
        return True

    def _activate_row_for_edit(self, row: int, *, allow_toggle: bool = True):
        account = self.list_model.account_at(row)
        if account is None:
            return

        if allow_toggle and self._is_editor_panel_open() and self._left_mode == "edit" and self.account is not None:
            current_pk = getattr(self.account, "pk", None)
            clicked_pk = getattr(account, "pk", None)
            if clicked_pk is not None and clicked_pk == current_pk:
                self._close_editor_panel()
                return

        self.list_model.set_selected_row(row)
        self.account = account
        self._set_left_mode("edit")
        self._open_editor_panel()
        res = fill_company_form(self, account)
        MessageHandler.show(self, res, only_errors=True)
        self.apply_platform_rules(self.platform_input.currentText())
        self.btn_delete.setEnabled(True)
        self._sync_card_spin_state()

    def clear_form(self, _checked: bool = False, mode: str | None = "new"):
        self.account = None
        self.seller_id_input.clear()
        self.comp_name_input.clear()
        self.api_key_input.clear()
        self.api_secret_input.clear()
        self.integration_code_input.clear()
        self.token_input.clear()
        self.extra_config_input.clear()
        if account_default_platform_label():
            self.platform_input.setCurrentText(account_default_platform_label())
        else:
            self.platform_input.setCurrentText("")
        self.is_active_input.setChecked(True)
        self.logo_path = None
        self.logo_selector.clearFiles()
        self.list_model.set_selected_row(None)
        self.btn_delete.setEnabled(False)
        if mode is not None:
            self._set_left_mode(mode)
        self._sync_card_spin_state()

    def apply_platform_rules(self, platform: str):
        try:
            enabled = get_platform_enabled_fields(platform)

            for name, (label, widget) in getattr(self, "_account_form_rows", {}).items():
                should_show = name in enabled
                label.setVisible(should_show)
                widget.setVisible(should_show)
                widget.setEnabled(should_show)

        except Exception as e:
            MessageHandler.show(self, Result.fail(map_error_to_message(e), error=e), only_errors=True)

    def _on_logo_files_changed(self, paths: list[str]):
        selected = [p for p in (paths or []) if p]
        if not selected:
            self.logo_path = None
            return

        file_path = selected[-1]
        res = handle_logo_selection(self, file_path)
        MessageHandler.show(self, res, only_errors=True)
        if not res.success:
            self.logo_selector.clearFiles()

    def on_submit(self):
        values, validation = collect_form_values(self)
        if not values:
            MessageHandler.show(self, validation, only_errors=True)
            return

        account_pk = getattr(getattr(self, "account", None), "pk", None)
        created_mode = account_pk is None
        self._set_submit_busy(True)
        self.health_status_label.setText(str(ui_text("account.submit.running", ACCOUNT_SUBMIT_RUNNING_TEXT)))

        worker = SyncWorker(
            submit_company_values,
            account_pk=account_pk,
            values=values,
            parent=self,
        )
        self._submit_worker = self._track_worker("_submit_worker", worker)

        def _after(res: Result) -> None:
            self._set_submit_busy(False)
            MessageHandler.show(self, res)
            if not res.success:
                return
            if account_pk is not None:
                self._pending_select_pk = account_pk
            self._reload_list()
            if created_mode:
                self.clear_form()

        def _finished() -> None:
            self._set_submit_busy(False)

        worker.result_ready.connect(_after)
        worker.finished.connect(_finished)
        worker.start()

    def delete_company(self):
        if self.account is None:
            MessageHandler.show(self, Result.fail(ACCOUNT_DELETE_NO_SELECTION_MESSAGE, close_dialog=False), only_errors=True)
            return
        confirm = AppMessageCenter.confirm(
            self,
            ACCOUNT_DELETE_CONFIRM_TITLE,
            ACCOUNT_DELETE_CONFIRM_MESSAGE_TEMPLATE.format(name=getattr(self.account, "comp_name", "")),
            default_yes=False,
        )
        if confirm:
            result = delete_company_and_refresh(None, self.account.pk)
            MessageHandler.show(self, result)
            if result.success:
                self.clear_form()
                self._reload_list()




