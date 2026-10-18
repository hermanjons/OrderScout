from __future__ import annotations

import os
from pathlib import Path
from threading import Event
from typing import Any, Optional

from PyQt6.QtCore import Qt, QSignalBlocker, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from AI.constants import ui_constants as ai_ui
from AI.processors.cloud_runtime import provider_reasoning_capabilities
from Core.threads.sync_worker import SyncWorker
from Core.views import (
    AppMessageCenter,
    RecordWorkspaceBehaviorAdapter,
    RecordWorkspaceCardRecord,
    RecordWorkspaceScaffold,
    SwitchSelectWidget,
    compose_record_workspace_style,
    optimized_table_updates,
)
from Feedback.processors.pipeline import MessageHandler, Result
from settings import ASSETS_DIR


class _AiActionsProxy:
    def __getattr__(self, name: str):
        import AI.views.actions as actions

        return getattr(actions, name)


ai_actions = _AiActionsProxy()


def _safe_text(value: Any, default: str = "-") -> str:
    text = str(value or "").strip()
    return text or default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _asset_path(filename: str, fallback: str = "") -> str:
    preferred = os.path.join(str(ASSETS_DIR), filename)
    if filename and os.path.exists(preferred):
        return preferred
    if fallback:
        fallback_path = os.path.join(str(ASSETS_DIR), fallback)
        if os.path.exists(fallback_path):
            return fallback_path
    return preferred


def _ai_icon_path() -> str:
    return _asset_path("ai-icon-search.png", "orderscout-logo.png")


def _mask_api_key(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    if len(raw) <= 8:
        return "****"
    return f"{raw[:4]}...{raw[-4:]}"


def _render_chip_html(values: list[str], *, color: str = "#2563EB", empty_text: str = "-") -> str:
    items = [str(item or "").strip() for item in list(values or []) if str(item or "").strip()]
    if not items:
        return f'<span style="color:#64748B;">{empty_text}</span>'
    chips: list[str] = []
    for item in items:
        chips.append(
            f'<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 10px;'
            f'border:1px solid {color};border-radius:11px;color:{color};font-weight:700;'
            f'font-size:11px;background:rgba(255,255,255,0.94);">{item}</span>'
        )
    return "".join(chips)


class _AiDownloadWorker(QThread):
    progress_changed = pyqtSignal(int, str)
    result_ready = pyqtSignal(object)

    def __init__(self, *, repo_id: str, filename: str, download_root: str, parent=None):
        super().__init__(parent)
        self.repo_id = str(repo_id or "").strip()
        self.filename = str(filename or "").strip()
        self.download_root = str(download_root or "").strip()
        self._pause_requested = Event()

    def request_pause(self) -> None:
        self._pause_requested.set()

    def run(self) -> None:
        try:
            def _progress(current: int, total: int, label: str) -> None:
                total_safe = max(int(total or 0), 1)
                percent = 0 if int(total or 0) <= 0 else int((int(current or 0) / total_safe) * 100)
                self.progress_changed.emit(max(0, min(100, percent)), str(label or ai_ui.AI_MANAGER_DOWNLOADING_TEXT))

            res = ai_actions.action_download_hf_model(
                repo_id=self.repo_id,
                filename=self.filename,
                download_root=self.download_root,
                progress_callback=_progress,
                pause_requested=self._pause_requested.is_set,
            )
            self.result_ready.emit(res)
        except Exception as exc:
            self.result_ready.emit(Result.fail(str(exc), error=exc, close_dialog=False))


class AIWorkspaceBehaviorAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, dialog: "AIManagerDialog") -> None:
        self.dialog = dialog

    @property
    def list_widget(self):
        return self.dialog.records_list

    def get_mode(self) -> str:
        return self.dialog._provider_mode

    def set_mode(self, mode: str) -> None:
        self.dialog._set_provider_mode(mode)

    def get_active_key(self) -> str:
        return self.dialog._active_workspace_key

    def get_selected_count(self) -> int:
        return len(self.dialog._selected_cloud_record_ids())

    def get_record_key(self, record) -> str:
        return str(getattr(record, "recordKey", "") or "")

    def prepare_new(self) -> None:
        self.dialog._set_entry_kind("cloud")
        self.dialog._reset_provider_form()

    def edit_without_active(self) -> None:
        self.dialog.provider_status.setText(ai_ui.AI_MANAGER_LEFT_EDIT_HINT)

    def activate_record(self, record) -> None:
        self.dialog._activate_workspace_record(record)

    def clear_active(self) -> None:
        self.dialog._clear_active_workspace_record()

    def apply_selection(self, record, selected: bool) -> None:
        self.dialog.records_list.set_record_selected(record, bool(selected))
        self.dialog._update_bulk_panel_state()

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self.dialog.records_list.set_select_button_guide_enabled(bool(enabled))

    def on_state_changed(self) -> None:
        self.dialog._update_provider_buttons()
        self.dialog._refresh_left_panel_header()

    def edit_guidance_message(self) -> str:
        return ai_ui.AI_MANAGER_LEFT_EDIT_HINT

    def bulk_guidance_message(self) -> str:
        return ai_ui.AI_MANAGER_LEFT_BULK_HINT


class AIManagerDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(ai_ui.AI_MANAGER_DIALOG_TITLE)
        self.setMinimumSize(ai_ui.AI_MANAGER_MIN_WIDTH, ai_ui.AI_MANAGER_MIN_HEIGHT)
        self.resize(ai_ui.AI_MANAGER_START_WIDTH, ai_ui.AI_MANAGER_START_HEIGHT)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        icon_path = _ai_icon_path()
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._settings: dict[str, Any] = {}
        self._selected_detail: dict[str, Any] = {}
        self._search_records: list[dict[str, Any]] = []
        self._provider_records: list[dict[str, Any]] = []
        self._library_records: list[dict[str, Any]] = []
        self._workspace_card_records: list[RecordWorkspaceCardRecord] = []
        self._active_workspace_key = ""
        self._active_workspace_payload: dict[str, Any] = {}
        self._provider_mode = "edit"
        self._provider_current_id: Optional[int] = None
        provider_specs_result = ai_actions.action_list_provider_connection_specs()
        self._provider_specs = list(
            (provider_specs_result.data or {}).get("records") or []
        ) if provider_specs_result.success else []
        if not self._provider_specs:
            raise RuntimeError("Provider baglanti katalogu bos olamaz.")

        self._search_worker: Optional[SyncWorker] = None
        self._detail_worker: Optional[SyncWorker] = None
        self._settings_worker: Optional[SyncWorker] = None
        self._save_settings_worker: Optional[SyncWorker] = None
        self._library_worker: Optional[SyncWorker] = None
        self._provider_models_worker: Optional[SyncWorker] = None
        self._download_worker: Optional[_AiDownloadWorker] = None
        self._is_disposing = False

        self._setup_styles()
        self._build_ui()
        self._set_provider_mode("new")
        self._load_settings()
        self._load_provider_accounts()
        self._refresh_library()
        self._start_search(initial=True)

    def _setup_styles(self) -> None:
        self.setStyleSheet(
            compose_record_workspace_style(
                """
                QDialog {
                    background-color: #F3F4F6;
                    color: #111827;
                }
                QFrame#HubHeader {
                    background: #FFFFFF;
                    border: 0;
                    border-bottom: 1px solid #D1D5DB;
                }
                QLabel#HubTitle {
                    color: #07111F;
                    font-size: 20px;
                    font-weight: 900;
                }
                QLabel#StatusPill {
                    background: rgba(15,23,42,0.05);
                    border: 1px solid rgba(148,163,184,0.26);
                    border-radius: 12px;
                    padding: 5px 10px;
                    color: #0F172A;
                    font-weight: 800;
                }
                QLabel#SmallPill {
                    background: rgba(37,99,235,0.08);
                    border: 1px solid rgba(37,99,235,0.20);
                    border-radius: 12px;
                    padding: 5px 10px;
                    color: #1D4ED8;
                    font-weight: 800;
                }
                QLabel#SummaryBanner {
                    background: #F8FAFC;
                    border: 1px solid #E2E8F0;
                    border-radius: 12px;
                    padding: 10px 12px;
                    color: #334155;
                    font-size: 12px;
                }
                QLabel#AiValidationMessage {
                    background: #FEF2F2;
                    border: 1px solid #FECACA;
                    border-radius: 10px;
                    padding: 8px 10px;
                    color: #B91C1C;
                    font-size: 12px;
                    font-weight: 800;
                }
                QLineEdit#Input[validationError="true"] {
                    border: 1px solid #EF4444;
                    background: #FFF7F7;
                }
                QLabel#FieldKey {
                    font-size: 12px;
                    font-weight: 700;
                    color: #0F172A;
                }
                QLineEdit#Search {
                    background: #FFFFFF;
                    border: 1px solid #BFDBFE;
                    border-radius: 12px;
                    padding: 0 14px;
                    min-height: 38px;
                    color: #0F172A;
                }
                QLineEdit#Input, QComboBox#Combo {
                    background: #FFFFFF;
                    border: 1px solid #CBD5E1;
                    border-radius: 12px;
                    padding: 8px 10px;
                    min-height: 22px;
                    color: #0F172A;
                }
                QLineEdit#Input:focus, QLineEdit#Search:focus {
                    border: 1px solid #60A5FA;
                }
                QPushButton#ModeTab {
                    background: #FFFFFF;
                    color: #334155;
                    border: 1px solid #CBD5E1;
                    border-radius: 14px;
                    padding: 0 16px;
                    font-weight: 800;
                    min-height: 38px;
                }
                QPushButton#ModeTab:checked {
                    background: #EFF6FF;
                    color: #1D4ED8;
                    border: 1px solid #60A5FA;
                }
                QListWidget#ModelResults {
                    background: #FFFFFF;
                    border: 1px solid #E5E7EB;
                    border-radius: 12px;
                }
                QListWidget#ModelResults::item {
                    padding: 8px 10px;
                    margin: 3px;
                    border-radius: 8px;
                }
                QListWidget#ModelResults::item:selected {
                    background: #EFF6FF;
                    color: #111827;
                }
                QProgressBar {
                    background: #E2E8F0;
                    border: none;
                    border-radius: 8px;
                    text-align: center;
                    min-height: 18px;
                }
                QProgressBar::chunk {
                    background: #2563EB;
                    border-radius: 8px;
                }
                """
            )
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame(self)
        header.setObjectName("HubHeader")
        header.setFixedHeight(72)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(16)
        logo = QLabel(header)
        logo.setFixedSize(44, 44)
        icon_path = _ai_icon_path()
        if os.path.exists(icon_path):
            logo.setPixmap(QIcon(icon_path).pixmap(42, 42))
        header_layout.addWidget(logo)
        title = QLabel("AI Model Hub")
        title.setObjectName("HubTitle")
        header_layout.addWidget(title)
        subtitle = QLabel("Yalnız provider bağlantıları ve yerel model indirmeleri")
        subtitle.setObjectName("Muted")
        header_layout.addWidget(subtitle)
        header_layout.addStretch(1)
        root.addWidget(header)

        self._workspace_host = QWidget(self)
        workspace_layout = QVBoxLayout(self._workspace_host)
        workspace_layout.setContentsMargins(16, 16, 16, 16)
        workspace_layout.setSpacing(0)
        root.addWidget(self._workspace_host, 1)

        self._workspace = RecordWorkspaceScaffold(
            self,
            left_title="Yeni kaynak",
            left_subtitle="Cloud API hesabı bağla veya yerel model indir.",
            filters_title="Filtreler",
            filters_subtitle=ai_ui.AI_MANAGER_HEADER_SUBTITLE,
            records_title="Bağlı kaynaklar",
            records_subtitle="Credential durumu ve yerel indirme kataloğu. Model seçimi Chat ekranındadır.",
            empty_placeholder_text="Gösterilecek AI kaydı bulunamadı.",
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
            style_sheet=None,
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": ai_ui.AI_MANAGER_SIDEBAR_NEW_TOOLTIP,
                    "icon_path": _asset_path("yeni-kayit.png", "ai-icon-search.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": ai_ui.AI_MANAGER_SIDEBAR_EDIT_TOOLTIP,
                    "icon_path": _asset_path("duzenleme-icon.png", "ai-icon-search.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "bulk",
                    "text": "",
                    "tooltip": ai_ui.AI_MANAGER_SIDEBAR_BULK_TOOLTIP,
                    "icon_path": _asset_path("toplu-secim (2).png", "ai-icon-search.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
            ),
            shell_kwargs={
                "left_stick_size": 454,
                "left_collapse_trigger": 250,
                "sidebar_width": 92,
            },
        )
        workspace_layout.addWidget(self._workspace, 1)
        self._workspace.editor_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._provider_sidebar = self._workspace.sidebar
        self.left_panel_title = self._workspace.left_card.title_label
        self.left_panel_hint = self._workspace.left_card.subtitle_label
        self.bulk_panel = self._workspace.bulk_panel
        self.records_list = self._workspace.list_widget
        self.provider_list = QListWidget(self)
        self.provider_list.hide()
        self.provider_count_pill = QLabel(self)
        self.provider_count_pill.hide()
        self.cloud_accounts_status = QLabel(self)
        self.cloud_accounts_status.hide()
        self.library_status = QLabel(self)
        self.library_status.hide()

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text=ai_ui.AI_MANAGER_CLEAR_TEXT,
            save_new_text="Bağlantıyı doğrula ve kaydet",
            save_edit_text="Bağlantıyı doğrula ve kaydet",
            delete_text=ai_ui.AI_MANAGER_DELETE_TEXT,
        )
        self.btn_reset_provider = self._workspace.editor_action_bar.clear_button
        self.btn_save_provider = self._workspace.editor_action_bar.save_button
        self.btn_delete_provider = self._workspace.editor_action_bar.delete_button
        self.btn_reset_provider.hide()
        action_layout = self._workspace.editor_action_bar.layout()
        if action_layout is not None and action_layout.count() >= 4:
            action_layout.takeAt(1)
            action_layout.setStretch(action_layout.indexOf(self.btn_save_provider), 1)
        self.btn_save_provider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._workspace.editor_action_bar.clearRequested.connect(self._on_editor_clear_requested)
        self._workspace.editor_action_bar.saveRequested.connect(self._on_editor_save_requested)
        self._workspace.editor_action_bar.deleteRequested.connect(self._on_editor_delete_requested)

        self._workspace.set_editor_widget(self._build_workspace_editor())
        self._workspace.set_bulk_widget(self._build_workspace_bulk_panel())
        self._workspace.set_filters_widget(self._build_workspace_filters())
        self._workspace.footer_bar.setObjectName("BottomBar")
        self._workspace.footer_bar.page_size_label.setText("Sayfa başına")
        self._workspace.filters_card.hide()
        self._workspace.footer_bar.hide()
        self.hub_scope_note = QLabel(
            "Bu ekrandan kaldırılanlar: aktif model seçimi, free/paid filtreleme, "
            "reasoning/zekâ seviyesi, fallback, context ve runtime ayarları. "
            "Bunların tamamı Chat ekranındaki Model seçimi panelindedir."
        )
        self.hub_scope_note.setObjectName("SummaryBanner")
        self.hub_scope_note.setWordWrap(True)
        self._workspace.records_card.body_layout.addWidget(self.hub_scope_note)

        self._workspace_adapter = AIWorkspaceBehaviorAdapter(self)
        self._workspace_behavior = self._workspace.create_behavior_controller(adapter=self._workspace_adapter)
        self._workspace.shell.splitter.setSizes([440, 1260])

    def _build_workspace_editor(self) -> QWidget:
        self.provider_editor = QWidget(self._workspace.editor_host)
        self.provider_editor.setObjectName("FormBody")
        layout = QVBoxLayout(self.provider_editor)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(20)

        self.provider_status = QLabel(ai_ui.AI_MANAGER_READY_TEXT)
        self.provider_status.setObjectName("StatusPill")
        self.provider_status.setWordWrap(True)
        layout.addWidget(self.provider_status)
        self.provider_status.hide()

        self.entry_tabs_frame = QFrame(self.provider_editor)
        self.entry_tabs_frame.setObjectName("SoftCard")
        entry_tabs_layout = QHBoxLayout(self.entry_tabs_frame)
        entry_tabs_layout.setContentsMargins(8, 8, 8, 8)
        entry_tabs_layout.setSpacing(8)
        self.btn_entry_cloud = QPushButton("Cloud bağlantısı")
        self.btn_entry_cloud.setObjectName("ModeTab")
        self.btn_entry_cloud.setCheckable(True)
        self.btn_entry_cloud.clicked.connect(lambda: self._set_entry_kind("cloud"))
        self.btn_entry_local = QPushButton("Yerel indirme")
        self.btn_entry_local.setObjectName("ModeTab")
        self.btn_entry_local.setCheckable(True)
        self.btn_entry_local.clicked.connect(lambda: self._set_entry_kind("local"))
        entry_tabs_layout.addWidget(self.btn_entry_cloud, 1)
        entry_tabs_layout.addWidget(self.btn_entry_local, 1)
        layout.addWidget(self.entry_tabs_frame)

        self.entry_stack_host = QWidget(self.provider_editor)
        self.entry_stack = QStackedLayout(self.entry_stack_host)
        self.entry_stack.setContentsMargins(0, 0, 0, 0)
        self.entry_stack.addWidget(self._build_cloud_entry_form())
        self.entry_stack.addWidget(self._build_local_entry_form())
        layout.addWidget(self.entry_stack_host)
        layout.addStretch(1)
        return self.provider_editor

    def _build_workspace_bulk_panel(self) -> QWidget:
        host = QWidget(self._workspace.bulk_panel)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        layout.addWidget(QLabel(ai_ui.AI_MANAGER_BULK_TITLE, objectName="SectionTitle"))
        self.bulk_summary = QLabel(ai_ui.AI_MANAGER_BULK_SUMMARY_TEMPLATE.format(count=0))
        self.bulk_summary.setObjectName("StatusPill")
        self.bulk_hint = QLabel(ai_ui.AI_MANAGER_BULK_HINT)
        self.bulk_hint.setObjectName("Muted")
        self.bulk_hint.setWordWrap(True)
        self.btn_bulk_delete = QPushButton(ai_ui.AI_MANAGER_BULK_DELETE_TEXT)
        self.btn_bulk_delete.setObjectName("Danger")
        self.btn_bulk_delete.clicked.connect(self._delete_bulk_selected)
        self.btn_bulk_clear = QPushButton(ai_ui.AI_MANAGER_BULK_CLEAR_TEXT)
        self.btn_bulk_clear.setObjectName("Secondary")
        self.btn_bulk_clear.clicked.connect(self._clear_provider_selection)
        layout.addWidget(self.bulk_summary)
        layout.addWidget(self.bulk_hint)
        layout.addWidget(self.btn_bulk_delete)
        layout.addWidget(self.btn_bulk_clear)
        layout.addStretch(1)
        return host

    def _build_workspace_filters(self) -> QWidget:
        host = QWidget(self._workspace.filters_host)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.records_filter_input = QLineEdit()
        self.records_filter_input.setObjectName("Search")
        self.records_filter_input.setPlaceholderText("Genel ara...")
        self.records_filter_input.textChanged.connect(self._apply_workspace_filters)
        self.records_type_combo = SwitchSelectWidget(title="Tip", all_text="Tümü", multi=False, include_all=True)
        self.records_type_combo.addItem("Cloud", "cloud")
        self.records_type_combo.addItem("Local", "local")
        self.records_type_combo.currentIndexChanged.connect(self._apply_workspace_filters)
        self.records_provider_combo = SwitchSelectWidget(title="Provider", all_text="Tümü", multi=False, include_all=True)
        self.records_provider_combo.currentIndexChanged.connect(self._apply_workspace_filters)
        self.records_status_combo = SwitchSelectWidget(title="Durum", all_text="Tümü", multi=False, include_all=True)
        self.records_status_combo.addItem(ai_ui.AI_MANAGER_ENABLED_TEXT, "enabled")
        self.records_status_combo.addItem(ai_ui.AI_MANAGER_DISABLED_TEXT, "disabled")
        self.records_status_combo.addItem(ai_ui.AI_MANAGER_LIBRARY_READY_TEXT, "ready")
        self.records_status_combo.addItem(ai_ui.AI_MANAGER_LIBRARY_MISSING_TEXT, "missing")
        self.records_status_combo.currentIndexChanged.connect(self._apply_workspace_filters)
        self.btn_reset_filters = QPushButton("Filtreyi Sıfırla")
        self.btn_reset_filters.setObjectName("SoftDanger")
        self.btn_reset_filters.clicked.connect(self._reset_workspace_filters)
        top.addWidget(self.records_filter_input, 1)
        top.addWidget(self.records_type_combo)
        top.addWidget(self.records_provider_combo)
        top.addWidget(self.records_status_combo)
        top.addWidget(self.btn_reset_filters)
        layout.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self._header_status = QLabel(ai_ui.AI_MANAGER_READY_TEXT)
        self._header_status.setObjectName("StatusPill")
        self.asset_cloud_count_pill = QLabel(ai_ui.AI_MANAGER_CLOUD_COUNT_TEMPLATE.format(count=0))
        self.asset_cloud_count_pill.setObjectName("SmallPill")
        self.asset_local_count_pill = QLabel(ai_ui.AI_MANAGER_LOCAL_COUNT_TEMPLATE.format(count=0))
        self.asset_local_count_pill.setObjectName("SmallPill")
        self.btn_choose_root = QPushButton(ai_ui.AI_MANAGER_CHOOSE_FOLDER_TEXT)
        self.btn_choose_root.setObjectName("Ghost")
        self.btn_choose_root.clicked.connect(self._on_choose_root)
        self.btn_open_root = QPushButton(ai_ui.AI_MANAGER_OPEN_FOLDER_TEXT)
        self.btn_open_root.setObjectName("Ghost")
        self.btn_open_root.clicked.connect(self._open_current_root)
        self.btn_refresh_library = QPushButton(ai_ui.AI_MANAGER_REFRESH_LIBRARY_TEXT)
        self.btn_refresh_library.setObjectName("Ghost")
        self.btn_refresh_library.clicked.connect(self._refresh_library)
        self.btn_open_selected_folder = QPushButton(ai_ui.AI_MANAGER_OPEN_SELECTED_FOLDER_TEXT)
        self.btn_open_selected_folder.setObjectName("Ghost")
        self.btn_open_selected_folder.clicked.connect(self._open_selected_library_folder)
        bottom.addWidget(self._header_status)
        bottom.addWidget(self.asset_cloud_count_pill)
        bottom.addWidget(self.asset_local_count_pill)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_refresh_library)
        bottom.addWidget(self.btn_choose_root)
        bottom.addWidget(self.btn_open_root)
        bottom.addWidget(self.btn_open_selected_folder)
        layout.addLayout(bottom)

        self.download_root_value = QLabel(ai_ui.AI_MANAGER_DOWNLOAD_ROOT_LOADING_TEXT)
        self.download_root_value.setObjectName("Muted")
        self.download_root_value.setWordWrap(True)
        layout.addWidget(self.download_root_value)
        return host

    def _build_provider_zone(self) -> QWidget:
        host = QWidget(self)
        host.setFixedWidth(454)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._provider_sidebar = SplitPanelSidebar(self, sidebar_width=92)
        self._provider_sidebar.add_panel_button(
            "new",
            "",
            tooltip=ai_ui.AI_MANAGER_SIDEBAR_NEW_TOOLTIP,
            icon_path=_asset_path("yeni-kayit.png", "ai-icon-search.png"),
            shape="circular",
            icon_scale=1.28,
        )
        self._provider_sidebar.add_panel_button(
            "edit",
            "",
            tooltip=ai_ui.AI_MANAGER_SIDEBAR_EDIT_TOOLTIP,
            icon_path=_asset_path("duzenleme-icon.png", "ai-icon-search.png"),
            shape="circular",
            icon_scale=1.28,
        )
        self._provider_sidebar.add_panel_button(
            "bulk",
            "",
            tooltip=ai_ui.AI_MANAGER_SIDEBAR_BULK_TOOLTIP,
            icon_path=_asset_path("toplu-secim (2).png", "ai-icon-search.png"),
            shape="circular",
            icon_scale=1.28,
        )
        self._provider_sidebar.panel_toggled.connect(self._on_provider_sidebar_toggled)
        row.addWidget(self._provider_sidebar)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        panel_host = QWidget(self)
        layout = QVBoxLayout(panel_host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QFrame(panel_host)
        header.setObjectName("ProviderCard")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(8)
        self.left_panel_title = QLabel(ai_ui.AI_MANAGER_LEFT_NEW_TITLE)
        self.left_panel_title.setObjectName("SectionTitle")
        self.left_panel_hint = QLabel(ai_ui.AI_MANAGER_LEFT_NEW_HINT)
        self.left_panel_hint.setObjectName("Muted")
        self.left_panel_hint.setWordWrap(True)
        self.provider_status = QLabel(ai_ui.AI_MANAGER_READY_TEXT)
        self.provider_status.setObjectName("StatusPill")
        header_layout.addWidget(self.left_panel_title)
        header_layout.addWidget(self.left_panel_hint)
        header_layout.addWidget(self.provider_status)
        layout.addWidget(header)

        self.provider_editor = QFrame(panel_host)
        self.provider_editor.setObjectName("ProviderCard")
        editor_layout = QVBoxLayout(self.provider_editor)
        editor_layout.setContentsMargins(16, 14, 16, 14)
        editor_layout.setSpacing(10)

        self.entry_tabs_frame = QFrame(self.provider_editor)
        self.entry_tabs_frame.setObjectName("SoftCard")
        entry_tabs_layout = QHBoxLayout(self.entry_tabs_frame)
        entry_tabs_layout.setContentsMargins(8, 8, 8, 8)
        entry_tabs_layout.setSpacing(8)
        self.btn_entry_cloud = QPushButton("Cloud bağlantısı")
        self.btn_entry_cloud.setObjectName("ModeTab")
        self.btn_entry_cloud.setCheckable(True)
        self.btn_entry_cloud.clicked.connect(lambda: self._set_entry_kind("cloud"))
        self.btn_entry_local = QPushButton("Yerel indirme")
        self.btn_entry_local.setObjectName("ModeTab")
        self.btn_entry_local.setCheckable(True)
        self.btn_entry_local.clicked.connect(lambda: self._set_entry_kind("local"))
        entry_tabs_layout.addWidget(self.btn_entry_cloud, 1)
        entry_tabs_layout.addWidget(self.btn_entry_local, 1)
        editor_layout.addWidget(self.entry_tabs_frame)

        self.entry_stack_host = QWidget(self.provider_editor)
        self.entry_stack = QStackedLayout(self.entry_stack_host)
        self.entry_stack.setContentsMargins(0, 0, 0, 0)
        self.entry_stack.setStackingMode(QStackedLayout.StackingMode.StackOne)
        self.entry_stack.addWidget(self._build_cloud_entry_form())
        self.entry_stack.addWidget(self._build_local_entry_form())
        editor_layout.addWidget(self.entry_stack_host)
        layout.addWidget(self.provider_editor)

        self.bulk_panel = QFrame(panel_host)
        self.bulk_panel.setObjectName("ProviderCard")
        bulk_layout = QVBoxLayout(self.bulk_panel)
        bulk_layout.setContentsMargins(16, 14, 16, 14)
        bulk_layout.setSpacing(8)
        bulk_layout.addWidget(QLabel(ai_ui.AI_MANAGER_BULK_TITLE, objectName="SectionTitle"))
        self.bulk_summary = QLabel(ai_ui.AI_MANAGER_BULK_SUMMARY_TEMPLATE.format(count=0))
        self.bulk_summary.setObjectName("StatusPill")
        self.bulk_hint = QLabel(ai_ui.AI_MANAGER_BULK_HINT)
        self.bulk_hint.setObjectName("Muted")
        self.bulk_hint.setWordWrap(True)
        self.btn_bulk_delete = QPushButton(ai_ui.AI_MANAGER_BULK_DELETE_TEXT)
        self.btn_bulk_delete.setObjectName("Danger")
        self.btn_bulk_delete.clicked.connect(self._delete_bulk_selected)
        self.btn_bulk_clear = QPushButton(ai_ui.AI_MANAGER_BULK_CLEAR_TEXT)
        self.btn_bulk_clear.setObjectName("Secondary")
        self.btn_bulk_clear.clicked.connect(self._clear_provider_selection)
        bulk_layout.addWidget(self.bulk_summary)
        bulk_layout.addWidget(self.bulk_hint)
        bulk_layout.addWidget(self.btn_bulk_delete)
        bulk_layout.addWidget(self.btn_bulk_clear)
        self.bulk_panel.hide()
        layout.addWidget(self.bulk_panel)

        list_card = QFrame(panel_host)
        list_card.setObjectName("ProviderCard")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(16, 14, 16, 14)
        list_layout.setSpacing(8)
        list_top = QHBoxLayout()
        list_top.setSpacing(8)
        list_top.addWidget(QLabel(ai_ui.AI_MANAGER_CLOUD_ACCOUNTS_TITLE, objectName="SectionTitle"))
        self.provider_count_pill = QLabel(ai_ui.AI_MANAGER_PROVIDER_COUNT_TEMPLATE.format(count=0))
        self.provider_count_pill.setObjectName("SmallPill")
        list_top.addStretch(1)
        list_top.addWidget(self.provider_count_pill)
        list_layout.addLayout(list_top)

        self.provider_list = QListWidget()
        self.provider_list.setObjectName("ProviderList")
        self.provider_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.provider_list.itemSelectionChanged.connect(self._on_provider_selection_changed)
        self.provider_list.itemDoubleClicked.connect(lambda *_: self._open_selected_provider_for_edit())
        self.provider_list.setMinimumHeight(280)
        list_layout.addWidget(self.provider_list)

        self.provider_list_hint = QLabel(ai_ui.AI_MANAGER_PROVIDER_LIST_HINT)
        self.provider_list_hint.setObjectName("Muted")
        self.provider_list_hint.setWordWrap(True)
        list_layout.addWidget(self.provider_list_hint)
        layout.addWidget(list_card, 1)

        foot = QFrame(panel_host)
        foot.setObjectName("SoftCard")
        foot_layout = QVBoxLayout(foot)
        foot_layout.setContentsMargins(14, 12, 14, 12)
        foot_layout.setSpacing(6)
        foot_layout.addWidget(QLabel(ai_ui.AI_MANAGER_SHORT_NOTE_TITLE, objectName="SectionTitle"))
        foot_note = QLabel(ai_ui.AI_MANAGER_SHORT_NOTE_TEXT)
        foot_note.setObjectName("Muted")
        foot_note.setWordWrap(True)
        foot_layout.addWidget(foot_note)
        layout.addWidget(foot)

        layout.addStretch(1)
        scroll.setWidget(panel_host)
        row.addWidget(scroll, 1)
        return host

    def _build_cloud_entry_form(self) -> QWidget:
        host = QWidget(self.provider_editor)
        form = QFormLayout(host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(18)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.provider_type_combo = SwitchSelectWidget(multi=False, include_all=False, empty_text="Seçiniz")
        self.provider_label_input = QLineEdit()
        self.provider_label_input.setObjectName("Input")
        self.provider_label_input.setPlaceholderText(ai_ui.AI_MANAGER_PROVIDER_LABEL_PLACEHOLDER)
        self.provider_endpoint_input = QLineEdit()
        self.provider_endpoint_input.setObjectName("Input")
        self.provider_endpoint_input.setPlaceholderText(ai_ui.AI_MANAGER_PROVIDER_ENDPOINT_PLACEHOLDER)
        self.provider_model_input = QLineEdit()
        self.provider_model_input.setObjectName("Input")
        self.provider_model_input.setPlaceholderText(ai_ui.AI_MANAGER_PROVIDER_MODEL_PLACEHOLDER)
        self.provider_model_input.textChanged.connect(lambda _text: self._sync_provider_reasoning_control())
        self.provider_model_combo = QComboBox()
        self.provider_model_combo.setObjectName("Input")
        self.provider_model_combo.setMinimumContentsLength(32)
        self.provider_model_combo.currentIndexChanged.connect(self._on_provider_model_selected)
        self.provider_reasoning_combo = QComboBox()
        self.provider_reasoning_combo.setObjectName("Input")
        self.provider_reasoning_status = QLabel("Secili modelin thinking/reasoning destegi kontrol edilir.")
        self.provider_reasoning_status.setObjectName("Muted")
        self.provider_reasoning_status.setWordWrap(True)
        self.provider_free_only_checkbox = QCheckBox("Sadece ucretsiz modeller")
        self.provider_free_only_checkbox.setChecked(True)
        self.btn_load_provider_models = QPushButton("Modelleri Getir")
        self.btn_load_provider_models.setObjectName("AiSecondary")
        self.btn_load_provider_models.clicked.connect(self._load_provider_models)
        self.provider_models_status = QLabel("Provider modeli manuel yazilabilir veya listeden secilebilir.")
        self.provider_models_status.setObjectName("Muted")
        self.provider_models_status.setWordWrap(True)
        model_picker_row = QHBoxLayout()
        model_picker_row.setSpacing(8)
        model_picker_row.addWidget(self.provider_model_combo, 1)
        model_picker_row.addWidget(self.provider_free_only_checkbox)
        model_picker_row.addWidget(self.btn_load_provider_models)
        model_picker_host = QWidget(host)
        model_picker_host.setLayout(model_picker_row)
        self.provider_key_input = QLineEdit()
        self.provider_key_input.setObjectName("Input")
        self.provider_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.provider_key_input.setPlaceholderText(ai_ui.AI_MANAGER_PROVIDER_KEY_PLACEHOLDER)
        self.provider_enabled_combo = SwitchSelectWidget(multi=False, include_all=False, empty_text="Seçiniz")
        self.provider_enabled_combo.addItem(ai_ui.AI_MANAGER_ENABLED_TEXT, True)
        self.provider_enabled_combo.addItem(ai_ui.AI_MANAGER_DISABLED_TEXT, False)
        for spec in self._provider_specs:
            self.provider_type_combo.addItem(spec["label"], spec)
        self.provider_type_combo.currentIndexChanged.connect(self._on_provider_type_changed)

        self.provider_editor_note = QLabel(ai_ui.AI_MANAGER_PROVIDER_EDITOR_NOTE)
        self.provider_editor_note.setObjectName("Muted")
        self.provider_editor_note.setWordWrap(True)

        form.addRow(QLabel(ai_ui.AI_MANAGER_PROVIDER_LABEL, objectName="FieldKey"), self.provider_type_combo)
        form.addRow(QLabel(ai_ui.AI_MANAGER_LABEL_LABEL, objectName="FieldKey"), self.provider_label_input)
        form.addRow(QLabel(ai_ui.AI_MANAGER_API_KEY_LABEL, objectName="FieldKey"), self.provider_key_input)
        self.provider_validation_label = QLabel("")
        self.provider_validation_label.setObjectName("AiValidationMessage")
        self.provider_validation_label.setWordWrap(True)
        self.provider_validation_label.hide()
        form.addRow(self.provider_validation_label)
        scope_note = QLabel(
            "Model ve zekâ ayarı burada yapılmaz. Bağlantıyı kaydet; provider modelleri "
            "Chat ekranında otomatik listelensin."
        )
        scope_note.setObjectName("SummaryBanner")
        scope_note.setWordWrap(True)
        form.addRow(scope_note)
        self.provider_label_input.textChanged.connect(self._clear_provider_validation)
        self.provider_key_input.textChanged.connect(self._clear_provider_validation)

        for widget in (
            self.provider_endpoint_input,
            self.provider_model_input,
            self.provider_model_combo,
            self.provider_free_only_checkbox,
            self.btn_load_provider_models,
            model_picker_host,
            self.provider_models_status,
            self.provider_reasoning_combo,
            self.provider_reasoning_status,
            self.provider_enabled_combo,
            self.provider_editor_note,
        ):
            widget.hide()

        return host

    def _build_local_entry_form(self) -> QWidget:
        host = QWidget(self.provider_editor)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.local_search_panel = QWidget(host)
        search_layout = QVBoxLayout(self.local_search_panel)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(10)

        provider_key = QLabel(ai_ui.AI_MANAGER_PROVIDER_LABEL, objectName="FieldKey")
        self.local_provider_combo = SwitchSelectWidget(multi=False, include_all=False, empty_text="Seçiniz")
        self.local_provider_combo.addItem(ai_ui.AI_MANAGER_HF_PROVIDER_TEXT, ai_ui.AI_MANAGER_HF_PROVIDER_VALUE)
        search_layout.addWidget(provider_key)
        search_layout.addWidget(self.local_provider_combo)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("Search")
        self.search_input.setPlaceholderText(ai_ui.AI_MANAGER_HF_SEARCH_PLACEHOLDER)
        self.search_input.returnPressed.connect(self._start_search)
        self.sort_combo = SwitchSelectWidget(title="Sıralama", multi=False, include_all=False, empty_text="Seçiniz")
        self.sort_combo.addItem(ai_ui.AI_MANAGER_SORT_BEST_TEXT, ai_ui.AI_MANAGER_SORT_BEST_VALUE)
        self.sort_combo.addItem(ai_ui.AI_MANAGER_SORT_DOWNLOADS_TEXT, ai_ui.AI_MANAGER_SORT_DOWNLOADS_VALUE)
        self.sort_combo.addItem(ai_ui.AI_MANAGER_SORT_LIKES_TEXT, ai_ui.AI_MANAGER_SORT_LIKES_VALUE)
        self.sort_combo.currentIndexChanged.connect(self._rebuild_results_list)
        self.btn_search = QPushButton(ai_ui.AI_MANAGER_SEARCH_TEXT)
        self.btn_search.setObjectName("Primary")
        self.btn_search.clicked.connect(self._start_search)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.sort_combo)
        search_row.addWidget(self.btn_search)
        search_layout.addLayout(search_row)

        self._search_status = QLabel(ai_ui.AI_MANAGER_HF_SEARCH_READY_TEXT)
        self._search_status.setObjectName("Muted")
        search_layout.addWidget(self._search_status)

        self.results_status = QLabel(ai_ui.AI_MANAGER_RESULTS_WAITING_TEXT)
        self.results_status.setObjectName("SmallPill")
        search_layout.addWidget(self.results_status)

        self.results_list = QListWidget()
        self.results_list.setObjectName("ModelResults")
        self.results_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_list.setMinimumHeight(190)
        self.results_list.itemSelectionChanged.connect(self._on_result_selected)
        search_layout.addWidget(self.results_list)

        self.local_model_summary = QLabel(ai_ui.AI_MANAGER_MODEL_SUMMARY_EMPTY_TEXT)
        self.local_model_summary.setObjectName("SummaryBanner")
        self.local_model_summary.setWordWrap(True)
        search_layout.addWidget(self.local_model_summary)

        search_layout.addWidget(QLabel(ai_ui.AI_MANAGER_DOWNLOADABLE_FILE_LABEL, objectName="FieldKey"))
        self.file_combo = QComboBox()
        self.file_combo.setObjectName("Combo")
        search_layout.addWidget(self.file_combo)

        local_actions = QHBoxLayout()
        local_actions.setSpacing(8)
        self.btn_download = QPushButton(ai_ui.AI_MANAGER_DOWNLOAD_AND_SAVE_TEXT)
        self.btn_download.setObjectName("Primary")
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._start_download)
        self.btn_pause_download = QPushButton("İndirmeyi duraklat")
        self.btn_pause_download.setObjectName("Secondary")
        self.btn_pause_download.setEnabled(False)
        self.btn_pause_download.hide()
        self.btn_pause_download.clicked.connect(self._pause_download)
        self.btn_open_model_page = QPushButton(ai_ui.AI_MANAGER_OPEN_MODEL_PAGE_TEXT)
        self.btn_open_model_page.setObjectName("Ghost")
        self.btn_open_model_page.setEnabled(False)
        self.btn_open_model_page.clicked.connect(self._open_model_page)
        local_actions.addWidget(self.btn_download, 1)
        local_actions.addWidget(self.btn_pause_download)
        local_actions.addWidget(self.btn_open_model_page)
        search_layout.addLayout(local_actions)

        self.download_stage = QLabel(ai_ui.AI_MANAGER_DOWNLOAD_WAITING_TEXT)
        self.download_stage.setObjectName("Muted")
        self.download_progress = QProgressBar()
        self.download_progress.setMinimum(0)
        self.download_progress.setMaximum(100)
        self.download_progress.setValue(0)
        search_layout.addWidget(self.download_stage)
        search_layout.addWidget(self.download_progress)
        search_layout.addWidget(QLabel("YÜKLÜ YEREL MODELLER", objectName="FieldKey"))
        self.installed_local_list = QListWidget()
        self.installed_local_list.setObjectName("ModelResults")
        self.installed_local_list.setMinimumHeight(90)
        self.installed_local_list.setMaximumHeight(150)
        self.installed_local_list.itemSelectionChanged.connect(
            self._update_local_delete_button
        )
        search_layout.addWidget(self.installed_local_list)
        self.btn_delete_local_model = QPushButton("Seçili yerel modeli sil")
        self.btn_delete_local_model.setObjectName("SoftDanger")
        self.btn_delete_local_model.setEnabled(False)
        self.btn_delete_local_model.clicked.connect(self._delete_selected_local_model)
        search_layout.addWidget(self.btn_delete_local_model)
        layout.addWidget(self.local_search_panel)

        self.local_config_panel = QWidget(host)
        config_layout = QVBoxLayout(self.local_config_panel)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(10)

        self.local_config_title = QLabel("Model calisma ayarlari")
        self.local_config_title.setObjectName("SectionTitle")
        config_layout.addWidget(self.local_config_title)

        self.local_config_meta = QLabel("Secili lokal modelin gomulu llama.cpp, context, cikti ve kaynak limitleri.")
        self.local_config_meta.setObjectName("Muted")
        self.local_config_meta.setWordWrap(True)
        config_layout.addWidget(self.local_config_meta)

        self.local_capabilities_label = QLabel("-")
        self.local_capabilities_label.setObjectName("SummaryBanner")
        self.local_capabilities_label.setWordWrap(True)
        config_layout.addWidget(self.local_capabilities_label)

        runtime_form = QFormLayout()
        runtime_form.setContentsMargins(0, 0, 0, 0)
        runtime_form.setSpacing(8)

        self.local_runtime_strategy_combo = QComboBox()
        self.local_runtime_strategy_combo.setObjectName("Combo")
        self.local_runtime_strategy_combo.addItem("llama.cpp (gomulu)", "llama_cpp")
        self.local_runtime_strategy_combo.setEnabled(False)

        self.local_performance_preset_combo = QComboBox()
        self.local_performance_preset_combo.setObjectName("Combo")
        self.local_performance_preset_combo.addItem("Otomatik", "auto")
        self.local_performance_preset_combo.addItem("Eco", "eco")
        self.local_performance_preset_combo.addItem("Dengeli", "balanced")
        self.local_performance_preset_combo.addItem("Hizli", "fast")

        self.local_reasoning_effort_combo = QComboBox()
        self.local_reasoning_effort_combo.setObjectName("Combo")
        self.local_reasoning_effort_combo.addItem("Otomatik", "auto")
        self.local_reasoning_effort_combo.addItem("Low", "low")
        self.local_reasoning_effort_combo.addItem("Medium", "medium")
        self.local_reasoning_effort_combo.addItem("High", "high")

        self.local_ctx_input = QLineEdit()
        self.local_ctx_input.setObjectName("Input")
        self.local_max_tokens_input = QLineEdit()
        self.local_max_tokens_input.setObjectName("Input")
        self.local_thread_input = QLineEdit()
        self.local_thread_input.setObjectName("Input")
        self.local_batch_input = QLineEdit()
        self.local_batch_input.setObjectName("Input")
        self.local_gpu_input = QLineEdit()
        self.local_gpu_input.setObjectName("Input")
        self.local_keep_alive_input = QLineEdit()
        self.local_keep_alive_input.setObjectName("Input")

        runtime_form.addRow(QLabel("Runner", objectName="FieldKey"), self.local_runtime_strategy_combo)
        runtime_form.addRow(QLabel("Performans profili", objectName="FieldKey"), self.local_performance_preset_combo)
        runtime_form.addRow(QLabel("Dusunme effort", objectName="FieldKey"), self.local_reasoning_effort_combo)
        runtime_form.addRow(QLabel("Context", objectName="FieldKey"), self.local_ctx_input)
        runtime_form.addRow(QLabel("Max cevap token", objectName="FieldKey"), self.local_max_tokens_input)
        runtime_form.addRow(QLabel("CPU thread", objectName="FieldKey"), self.local_thread_input)
        runtime_form.addRow(QLabel("Batch", objectName="FieldKey"), self.local_batch_input)
        runtime_form.addRow(QLabel("GPU layer", objectName="FieldKey"), self.local_gpu_input)
        runtime_form.addRow(QLabel("Keep alive", objectName="FieldKey"), self.local_keep_alive_input)
        config_layout.addLayout(runtime_form)

        self.local_mmap_check = QCheckBox("Disk mmap kullan")
        self.local_mlock_check = QCheckBox("Bellege kilitle (mlock)")
        self.local_allow_unsafe_check = QCheckBox("Guvenlik limitini elle asmaya izin ver")
        config_layout.addWidget(self.local_mmap_check)
        config_layout.addWidget(self.local_mlock_check)
        config_layout.addWidget(self.local_allow_unsafe_check)

        self.local_resource_plan_summary = QLabel("-")
        self.local_resource_plan_summary.setObjectName("SummaryBanner")
        self.local_resource_plan_summary.setWordWrap(True)
        config_layout.addWidget(self.local_resource_plan_summary)

        pressure_row = QHBoxLayout()
        pressure_row.setSpacing(8)
        self.local_resource_pressure = QProgressBar()
        self.local_resource_pressure.setMinimum(0)
        self.local_resource_pressure.setMaximum(100)
        self.local_resource_pressure.setValue(0)
        self.local_resource_pressure.setFormat("%p% yuk")
        pressure_row.addWidget(self.local_resource_pressure, 1)
        self.local_performance_score_label = QLabel("0")
        self.local_performance_score_label.setObjectName("SmallPill")
        pressure_row.addWidget(self.local_performance_score_label)
        config_layout.addLayout(pressure_row)

        self.local_config_panel.hide()
        layout.addWidget(self.local_config_panel)
        return host

    def _build_hub_zone(self) -> QWidget:
        host = QWidget(self)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_header_card())
        layout.addWidget(self._build_asset_counts_card())
        layout.addWidget(self._build_cloud_accounts_overview_card())
        layout.addWidget(self._build_library_card(), 1)
        return host

    def _build_asset_counts_card(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("HubCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_col.addWidget(QLabel(ai_ui.AI_MANAGER_ASSETS_TITLE, objectName="SectionTitle"))
        hint = QLabel(ai_ui.AI_MANAGER_ASSETS_HINT)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        title_col.addWidget(hint)
        layout.addLayout(title_col, 1)

        self.asset_local_count_pill = QLabel(ai_ui.AI_MANAGER_LOCAL_COUNT_TEMPLATE.format(count=0))
        self.asset_local_count_pill.setObjectName("StatusPill")
        self.asset_cloud_count_pill = QLabel(ai_ui.AI_MANAGER_CLOUD_COUNT_TEMPLATE.format(count=0))
        self.asset_cloud_count_pill.setObjectName("StatusPill")
        layout.addWidget(self.asset_local_count_pill)
        layout.addWidget(self.asset_cloud_count_pill)
        return card

    def _build_cloud_accounts_overview_card(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("HubCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel(ai_ui.AI_MANAGER_LINKED_CLOUD_TITLE, objectName="SectionTitle"))
        top.addStretch(1)
        self.cloud_accounts_status = QLabel(ai_ui.AI_MANAGER_ACCOUNT_LIST_WAITING_TEXT)
        self.cloud_accounts_status.setObjectName("SmallPill")
        top.addWidget(self.cloud_accounts_status)
        layout.addLayout(top)

        self.cloud_accounts_table = QTableWidget(0, 4)
        self.cloud_accounts_table.setHorizontalHeaderLabels(list(ai_ui.AI_MANAGER_CLOUD_TABLE_HEADERS))
        self.cloud_accounts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cloud_accounts_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.cloud_accounts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cloud_accounts_table.verticalHeader().setVisible(False)
        self.cloud_accounts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.cloud_accounts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.cloud_accounts_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.cloud_accounts_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.cloud_accounts_table)
        return card

    def _build_header_card(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("HeroCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(4)
        title = QLabel(ai_ui.AI_MANAGER_DIALOG_TITLE)
        title.setObjectName("HubTitle")
        subtitle = QLabel(ai_ui.AI_MANAGER_HEADER_SUBTITLE)
        subtitle.setObjectName("HubSubTitle")
        subtitle.setWordWrap(True)
        left.addWidget(title)
        left.addWidget(subtitle)
        layout.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self._header_status = QLabel(ai_ui.AI_MANAGER_READY_TEXT)
        self._header_status.setObjectName("StatusPill")
        self.btn_choose_root = QPushButton(ai_ui.AI_MANAGER_CHOOSE_FOLDER_TEXT)
        self.btn_choose_root.setObjectName("Secondary")
        self.btn_choose_root.clicked.connect(self._on_choose_root)
        self.btn_open_root = QPushButton(ai_ui.AI_MANAGER_OPEN_FOLDER_TEXT)
        self.btn_open_root.setObjectName("Secondary")
        self.btn_open_root.clicked.connect(self._open_current_root)
        top.addStretch(1)
        top.addWidget(self._header_status)
        top.addWidget(self.btn_choose_root)
        top.addWidget(self.btn_open_root)

        self.download_root_value = QLabel(ai_ui.AI_MANAGER_DOWNLOAD_ROOT_LOADING_TEXT)
        self.download_root_value.setObjectName("Muted")
        self.download_root_value.setWordWrap(True)
        right.addLayout(top)
        right.addWidget(self.download_root_value)
        layout.addLayout(right, 0)
        return card

    def _build_search_card(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("HubCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(ai_ui.AI_MANAGER_SEARCH_PLACEHOLDER)
        self.search_input.returnPressed.connect(self._start_search)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem(ai_ui.AI_MANAGER_SORT_BEST_TEXT, ai_ui.AI_MANAGER_SORT_BEST_VALUE)
        self.sort_combo.addItem(ai_ui.AI_MANAGER_SORT_DOWNLOADS_TEXT, ai_ui.AI_MANAGER_SORT_DOWNLOADS_VALUE)
        self.sort_combo.addItem(ai_ui.AI_MANAGER_SORT_LIKES_TEXT, ai_ui.AI_MANAGER_SORT_LIKES_VALUE)
        self.sort_combo.currentIndexChanged.connect(self._rebuild_results_list)

        self.btn_search = QPushButton(ai_ui.AI_MANAGER_SEARCH_TEXT)
        self.btn_search.setObjectName("Primary")
        self.btn_search.clicked.connect(self._start_search)

        self.btn_refresh_library = QPushButton(ai_ui.AI_MANAGER_REFRESH_LIBRARY_TEXT)
        self.btn_refresh_library.setObjectName("Secondary")
        self.btn_refresh_library.clicked.connect(self._refresh_library)

        self._search_status = QLabel(ai_ui.AI_MANAGER_MODEL_SEARCH_READY_TEXT)
        self._search_status.setObjectName("Muted")

        layout.addWidget(self.search_input, 1)
        layout.addWidget(self.sort_combo)
        layout.addWidget(self.btn_search)
        layout.addWidget(self.btn_refresh_library)
        layout.addWidget(self._search_status)
        return card

    def _build_main_splitter(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_results_card())
        splitter.addWidget(self._build_detail_card())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([410, 650])
        return splitter

    def _build_results_card(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("HubCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel(ai_ui.AI_MANAGER_SEARCH_RESULTS_TITLE, objectName="SectionTitle"))
        self.results_status = QLabel(ai_ui.AI_MANAGER_RESULTS_WAITING_TEXT)
        self.results_status.setObjectName("SmallPill")
        top.addStretch(1)
        layout.addLayout(top)

        self.results_list = QListWidget()
        self.results_list.setObjectName("ModelResults")
        self.results_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_list.itemSelectionChanged.connect(self._on_result_selected)
        layout.addWidget(self.results_list, 1)
        return card

    def _build_detail_card(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("HubCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        title_col = QVBoxLayout()
        self.detail_title = QLabel(ai_ui.AI_MANAGER_MODEL_UNSELECTED_TITLE)
        self.detail_title.setObjectName("SectionTitle")
        self.detail_title.setStyleSheet("font-size: 22px; font-weight: 900; color: #111827;")
        self.detail_subtitle = QLabel(ai_ui.AI_MANAGER_MODEL_UNSELECTED_SUBTITLE)
        self.detail_subtitle.setObjectName("Muted")
        self.detail_subtitle.setWordWrap(True)
        title_col.addWidget(self.detail_title)
        title_col.addWidget(self.detail_subtitle)
        top.addLayout(title_col, 1)
        self.staff_pick_pill = QLabel(ai_ui.AI_MANAGER_MODEL_DETAIL_PILL)
        self.staff_pick_pill.setObjectName("SmallPill")
        top.addWidget(self.staff_pick_pill, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        meta_grid = QGridLayout()
        meta_grid.setHorizontalSpacing(14)
        meta_grid.setVerticalSpacing(8)
        self._repo_value = self._add_meta_row(meta_grid, 0, 0, "Repo")
        self._downloads_value = self._add_meta_row(meta_grid, 0, 2, ai_ui.AI_MANAGER_DETAIL_DOWNLOADS_LABEL)
        self._likes_value = self._add_meta_row(meta_grid, 2, 0, ai_ui.AI_MANAGER_DETAIL_LIKES_LABEL)
        self._updated_value = self._add_meta_row(meta_grid, 2, 2, ai_ui.AI_MANAGER_DETAIL_UPDATED_LABEL)
        self._pipeline_value = self._add_meta_row(meta_grid, 4, 0, ai_ui.AI_MANAGER_DETAIL_TYPE_LABEL)
        self._format_value = self._add_meta_row(meta_grid, 4, 2, ai_ui.AI_MANAGER_DETAIL_FILE_FOCUS_LABEL)
        layout.addLayout(meta_grid)

        self.capabilities_label = QLabel()
        self.capabilities_label.setTextFormat(Qt.TextFormat.RichText)
        self.capabilities_label.setWordWrap(True)
        layout.addWidget(self.capabilities_label)

        self.summary_box = QLabel(ai_ui.AI_MANAGER_MODEL_SUMMARY_TEXT)
        self.summary_box.setObjectName("SummaryBanner")
        self.summary_box.setWordWrap(True)
        layout.addWidget(self.summary_box)

        download_card = QFrame(self)
        download_card.setObjectName("SoftCard")
        download_layout = QVBoxLayout(download_card)
        download_layout.setContentsMargins(14, 12, 14, 12)
        download_layout.setSpacing(8)
        download_layout.addWidget(QLabel(ai_ui.AI_MANAGER_DOWNLOAD_OPTIONS_TITLE, objectName="SectionTitle"))
        download_layout.addWidget(QLabel(ai_ui.AI_MANAGER_DOWNLOAD_OPTIONS_HINT, objectName="Muted"))
        self.file_combo = QComboBox()
        download_layout.addWidget(self.file_combo)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.btn_download = QPushButton(ai_ui.AI_MANAGER_DOWNLOAD_TEXT)
        self.btn_download.setObjectName("Primary")
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._start_download)
        self.btn_open_model_page = QPushButton(ai_ui.AI_MANAGER_OPEN_MODEL_PAGE_TEXT)
        self.btn_open_model_page.setObjectName("Secondary")
        self.btn_open_model_page.setEnabled(False)
        self.btn_open_model_page.clicked.connect(self._open_model_page)
        action_row.addWidget(self.btn_download)
        action_row.addWidget(self.btn_open_model_page)
        action_row.addStretch(1)
        download_layout.addLayout(action_row)

        self.download_stage = QLabel(ai_ui.AI_MANAGER_DOWNLOAD_WAITING_TEXT)
        self.download_stage.setObjectName("Muted")
        self.download_progress = QProgressBar()
        self.download_progress.setMinimum(0)
        self.download_progress.setMaximum(100)
        self.download_progress.setValue(0)
        download_layout.addWidget(self.download_stage)
        download_layout.addWidget(self.download_progress)
        layout.addWidget(download_card)

        readme_card = QFrame(self)
        readme_card.setObjectName("SoftCard")
        readme_layout = QVBoxLayout(readme_card)
        readme_layout.setContentsMargins(14, 12, 14, 12)
        readme_layout.setSpacing(8)
        readme_layout.addWidget(QLabel(ai_ui.AI_MANAGER_README_TITLE, objectName="SectionTitle"))
        self.readme_box = QPlainTextEdit()
        self.readme_box.setReadOnly(True)
        self.readme_box.setMinimumHeight(180)
        readme_layout.addWidget(self.readme_box)
        layout.addWidget(readme_card, 1)
        return card

    def _build_library_card(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("HubCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel(ai_ui.AI_MANAGER_LIBRARY_TITLE, objectName="SectionTitle"))
        top.addStretch(1)
        self.library_status = QLabel(ai_ui.AI_MANAGER_LIBRARY_LOADING_TEXT)
        self.library_status.setObjectName("SmallPill")
        self.btn_open_selected_folder = QPushButton(ai_ui.AI_MANAGER_OPEN_SELECTED_FOLDER_TEXT)
        self.btn_open_selected_folder.setObjectName("Secondary")
        self.btn_open_selected_folder.clicked.connect(self._open_selected_library_folder)
        top.addWidget(self.library_status)
        top.addWidget(self.btn_open_selected_folder)
        layout.addLayout(top)

        self.library_table = QTableWidget(0, 6)
        self.library_table.setHorizontalHeaderLabels(list(ai_ui.AI_MANAGER_LIBRARY_TABLE_HEADERS))
        self.library_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.library_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.library_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.library_table.verticalHeader().setVisible(False)
        self.library_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.library_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.library_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.library_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.library_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.library_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.library_table.itemDoubleClicked.connect(lambda *_: self._open_selected_library_folder())
        layout.addWidget(self.library_table)
        return card

    def _add_meta_row(self, layout: QGridLayout, row: int, column: int, key: str) -> QLabel:
        key_label = QLabel(key)
        key_label.setObjectName("FieldKey")
        value_label = QLabel(ai_ui.AI_MANAGER_EMPTY_VALUE_TEXT)
        value_label.setObjectName("FieldValue")
        value_label.setWordWrap(True)
        layout.addWidget(key_label, row, column)
        layout.addWidget(value_label, row + 1, column)
        return value_label

    def _set_provider_mode(self, mode: str) -> None:
        if mode not in {"new", "edit", "bulk"}:
            mode = "new"

        self._provider_mode = mode
        self._provider_sidebar.set_active_panel(mode)
        self._workspace.set_editor_action_mode(mode)
        self.bulk_panel.setVisible(mode == "bulk")
        self._workspace.editor_scroll.setVisible(mode != "bulk")
        self.provider_editor.setVisible(mode != "bulk")
        self.provider_list.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection if mode == "bulk"
            else QAbstractItemView.SelectionMode.SingleSelection
        )

        if mode == "new":
            self.left_panel_title.setText("Yeni kaynak")
            self.left_panel_hint.setText("Cloud API hesabı bağla veya yerel model indir.")
            self.entry_tabs_frame.setVisible(True)
            self._set_entry_kind(getattr(self, "_entry_kind", "cloud"))
            self._reset_provider_form()
        elif mode == "edit":
            self.left_panel_title.setText(ai_ui.AI_MANAGER_LEFT_EDIT_TITLE)
            self.left_panel_hint.setText(ai_ui.AI_MANAGER_LEFT_EDIT_HINT)
            self.entry_tabs_frame.setVisible(False)
            if self._active_workspace_payload.get("kind") == "local":
                self._set_entry_kind("local")
                record = dict(self._active_workspace_payload.get("record") or {})
                self._set_local_form_mode("search")
                self.search_input.setText(_safe_text(record.get("repo_id"), ""))
                self.local_model_summary.setText(
                    f"{_safe_text(record.get('repo_id'), '-')}\n"
                    f"{_safe_text(record.get('filename'), '-')} · indirme kaydı hazır"
                )
            else:
                self._set_entry_kind("cloud")
                self._load_selected_provider_into_form()
        else:
            self.left_panel_title.setText(ai_ui.AI_MANAGER_LEFT_BULK_TITLE)
            self.left_panel_hint.setText(ai_ui.AI_MANAGER_LEFT_BULK_HINT)
            self.entry_tabs_frame.setVisible(False)
            self._update_bulk_panel_state()

        self._update_provider_buttons()

    def _set_local_form_mode(self, mode: str) -> None:
        if not hasattr(self, "local_search_panel") or not hasattr(self, "local_config_panel"):
            return
        del mode
        self.local_search_panel.setVisible(True)
        self.local_config_panel.setVisible(False)

    def _set_entry_kind(self, kind: str) -> None:
        if kind not in {"cloud", "local"}:
            kind = "cloud"
        self._entry_kind = kind
        self.btn_entry_cloud.setChecked(kind == "cloud")
        self.btn_entry_local.setChecked(kind == "local")
        self.entry_stack.setCurrentIndex(0 if kind == "cloud" else 1)
        # Local download owns its action inside the download form. Keeping the
        # generic record save bar visible here creates a second disabled action
        # with no distinct meaning.
        self._workspace.editor_action_bar.setVisible(kind == "cloud")
        if kind == "local":
            self._set_local_form_mode("search")
        self._update_provider_buttons()

    def _set_combo_data(self, combo: QComboBox, value: Any) -> None:
        target = str(value or "").strip()
        index = combo.findData(target)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _set_input_text(self, widget: QLineEdit, value: Any) -> None:
        widget.setText("" if value in (None, "") else str(value))

    def _populate_local_runtime_config(
        self,
        *,
        record: dict[str, Any],
        config: dict[str, Any],
        capabilities: dict[str, Any],
        resource_plan: dict[str, Any],
    ) -> None:
        repo_id = _safe_text(record.get("repo_id"), "-")
        filename = _safe_text(record.get("filename"), "-")
        self.local_config_title.setText(repo_id)
        self.local_config_meta.setText(f"{filename} | {_safe_text(record.get('file_format'), '-')} | {_safe_text(record.get('size_text'), '-')}")

        sources = ", ".join(str(item) for item in capabilities.get("runtime_sources") or []) or "llama_cpp"
        caps = [
            f"runner: {sources}",
            f"reasoning: {'var' if capabilities.get('supports_reasoning_effort') else 'yok'}",
            f"mmap: {'var' if capabilities.get('supports_mmap') else 'yok'}",
            f"keep_alive: {'var' if capabilities.get('supports_keep_alive') else 'yok'}",
        ]
        self.local_capabilities_label.setText(" | ".join(caps))

        self._set_combo_data(self.local_runtime_strategy_combo, config.get("runtime_strategy"))
        self._set_combo_data(self.local_performance_preset_combo, config.get("performance_preset"))
        self._set_combo_data(self.local_reasoning_effort_combo, config.get("reasoning_effort"))
        self.local_reasoning_effort_combo.setEnabled(bool(capabilities.get("supports_reasoning_effort")))

        self._set_input_text(self.local_ctx_input, config.get("num_ctx"))
        self._set_input_text(self.local_max_tokens_input, config.get("max_tokens"))
        self._set_input_text(self.local_thread_input, config.get("num_thread"))
        self._set_input_text(self.local_batch_input, config.get("num_batch"))
        self._set_input_text(self.local_gpu_input, config.get("num_gpu"))
        self._set_input_text(self.local_keep_alive_input, config.get("keep_alive"))
        self.local_mmap_check.setChecked(bool(config.get("use_mmap", True)))
        self.local_mmap_check.setEnabled(bool(capabilities.get("supports_mmap")))
        self.local_mlock_check.setChecked(bool(config.get("use_mlock", False)))
        self.local_allow_unsafe_check.setChecked(bool(config.get("allow_unsafe", False)))

        pressure = int(float(resource_plan.get("memory_pressure") or 0) * 100)
        self.local_resource_pressure.setValue(max(0, min(100, pressure)))
        self.local_performance_score_label.setText(f"skor {resource_plan.get('performance_score', 0)}")
        self.local_resource_plan_summary.setText(
            " | ".join(
                [
                    f"profil: {_safe_text(resource_plan.get('profile'), '-')}",
                    f"ctx {resource_plan.get('num_ctx', '-')}",
                    f"out {resource_plan.get('max_tokens', '-')}",
                    f"cpu {resource_plan.get('num_thread', '-')}",
                    f"gpu {resource_plan.get('num_gpu', '-')}",
                    f"offload {resource_plan.get('offload_strategy', '-')}",
                    f"mmap {'acik' if resource_plan.get('use_mmap') else 'kapali'}",
                ]
            )
        )

    def _load_local_model_config(self, record: dict[str, Any]) -> None:
        if not record:
            self.provider_status.setText("Lokal model kaydi secilmedi.")
            self._set_local_form_mode("search")
            return
        result = ai_actions.action_get_local_model_runtime_config(record)
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            self.provider_status.setText(result.message)
            return
        data = result.data or {}
        enriched = dict(data.get("record") or record)
        if self._active_workspace_payload.get("kind") == "local":
            self._active_workspace_payload["record"] = enriched
        self._populate_local_runtime_config(
            record=enriched,
            config=dict(data.get("config") or {}),
            capabilities=dict(data.get("capabilities") or {}),
            resource_plan=dict(data.get("resource_plan") or {}),
        )
        self._set_local_form_mode("config")
        self.provider_status.setText("Lokal model ayarlari duzenleniyor.")

    def _collect_local_runtime_config(self) -> dict[str, Any]:
        return {
            "runtime_strategy": self.local_runtime_strategy_combo.currentData(),
            "performance_preset": self.local_performance_preset_combo.currentData(),
            "reasoning_effort": self.local_reasoning_effort_combo.currentData(),
            "num_ctx": self.local_ctx_input.text(),
            "max_tokens": self.local_max_tokens_input.text(),
            "num_thread": self.local_thread_input.text(),
            "num_batch": self.local_batch_input.text(),
            "num_gpu": self.local_gpu_input.text(),
            "keep_alive": self.local_keep_alive_input.text(),
            "use_mmap": self.local_mmap_check.isChecked(),
            "use_mlock": self.local_mlock_check.isChecked(),
            "allow_unsafe": self.local_allow_unsafe_check.isChecked(),
        }

    def _save_local_model_config(self) -> None:
        record = dict((self._active_workspace_payload or {}).get("record") or {})
        if not record:
            self.provider_status.setText("Kaydedilecek lokal model yok.")
            return
        result = ai_actions.action_save_local_model_runtime_config(record, self._collect_local_runtime_config())
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            self.provider_status.setText(result.message)
            return
        data = result.data or {}
        self._settings = dict(data.get("settings") or self._settings)
        enriched = dict(data.get("record") or record)
        self._active_workspace_payload["record"] = enriched
        self._populate_local_runtime_config(
            record=enriched,
            config=dict(data.get("config") or {}),
            capabilities=dict(data.get("capabilities") or {}),
            resource_plan=dict(data.get("resource_plan") or {}),
        )
        self.provider_status.setText(result.message)
        self._refresh_library()

    def _provider_spec_for_code(self, code: str) -> dict[str, str]:
        clean_code = str(code or "").strip().lower()
        for spec in self._provider_specs:
            if spec["code"] == clean_code:
                return dict(spec)
        return dict(self._provider_specs[0])

    def _default_provider_spec(self) -> dict[str, str]:
        return dict(self._provider_specs[0])

    def _set_header_status(self, text: str) -> None:
        self._header_status.setText(_safe_text(text))

    def _load_settings(self) -> None:
        if self._settings_worker is not None and self._settings_worker.isRunning():
            return

        self.download_root_value.setText(ai_ui.AI_MANAGER_DOWNLOAD_ROOT_LOADING_TEXT)
        self._settings_worker = SyncWorker(ai_actions.action_load_ai_settings, parent=self)

        def _done(result: Result) -> None:
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self.download_root_value.setText(ai_ui.AI_MANAGER_DOWNLOAD_ROOT_LOAD_FAILED_TEXT)
                return

            self._settings = dict((result.data or {}).get("settings") or {})
            self.download_root_value.setText(_safe_text(self._settings.get("download_root"), "-"))
            self._set_header_status(ai_ui.AI_MANAGER_READY_TEXT)

        def _finished() -> None:
            self._settings_worker = None

        self._settings_worker.result_ready.connect(_done)
        self._settings_worker.finished.connect(_finished)
        self._settings_worker.start()

    def _on_editor_clear_requested(self) -> None:
        if self._provider_mode == "bulk":
            self._clear_provider_selection()
            return
        if getattr(self, "_entry_kind", "cloud") == "local":
            self._clear_detail()
            return
        self._reset_provider_form()

    def _on_editor_save_requested(self) -> None:
        if getattr(self, "_entry_kind", "cloud") == "local":
            self.provider_status.setText("Yerel model ayarları Chat ekranına taşındı; indirme panelini kullan.")
            return
        self._save_provider_account()

    def _on_editor_delete_requested(self) -> None:
        if getattr(self, "_entry_kind", "cloud") != "cloud":
            return
        self._delete_current_provider()

    def _workspace_record_payload(self, record) -> dict[str, Any]:
        payload = getattr(record, "payload", None)
        return payload if isinstance(payload, dict) else {}

    def _build_cloud_card(self, record: dict[str, Any]) -> RecordWorkspaceCardRecord:
        provider_id = _safe_int(record.get("id"), 0)
        status = ai_ui.AI_MANAGER_ENABLED_TEXT if bool(record.get("is_enabled")) else ai_ui.AI_MANAGER_DISABLED_TEXT
        title = _safe_text(record.get("label"), "-")
        provider = _safe_text(record.get("provider_label"), "-")
        return RecordWorkspaceCardRecord(
            orderNumber=f"cloud:{provider_id}",
            title=title,
            subtitle=provider,
            extra=(
                f"Cloud bağlantısı | {status} | credential güvenli saklanıyor | "
                f"{_safe_text(record.get('api_key_masked'), '-')}"
            ),
            logo_path=_ai_icon_path(),
            payload={"kind": "cloud", "id": provider_id, "record": dict(record), "status_key": "enabled" if bool(record.get("is_enabled")) else "disabled"},
            action_text="Bağlantıyı düzenle",
        )

    def _build_local_card(self, record: dict[str, Any]) -> RecordWorkspaceCardRecord:
        model_id = _safe_int(record.get("id"), 0)
        exists = bool(record.get("exists_on_disk"))
        status = ai_ui.AI_MANAGER_LIBRARY_READY_TEXT if exists else ai_ui.AI_MANAGER_LIBRARY_MISSING_TEXT
        return RecordWorkspaceCardRecord(
            orderNumber=f"local:{model_id}",
            title=_safe_text(record.get("repo_id"), "-"),
            subtitle=f"{_safe_text(record.get('filename'))} | {_safe_text(record.get('quantization'))}",
            extra=f"Yerel indirme | {_safe_text(record.get('file_format'))} | {_safe_text(record.get('size_text'))} | {status}",
            logo_path=_ai_icon_path(),
            payload={"kind": "local", "id": model_id, "record": dict(record), "status_key": "ready" if exists else "missing"},
        )

    def _build_local_library_card(self, records: list[dict[str, Any]]) -> RecordWorkspaceCardRecord:
        ready_count = sum(1 for record in records if bool(record.get("exists_on_disk")))
        return RecordWorkspaceCardRecord(
            orderNumber="local:library",
            title="Yerel model indirmeleri",
            subtitle=f"{ready_count} model hazır · Hugging Face araması",
            extra="Yerel indirme kataloğunu aç; model ve runtime ayarlarını Chat ekranında yap.",
            logo_path=_ai_icon_path(),
            payload={
                "kind": "local_library",
                "records": [dict(record) for record in records],
                "status_key": "ready" if ready_count else "missing",
            },
            action_text="Yerel indir",
        )

    def _sync_provider_filter_options(self) -> None:
        if not hasattr(self, "records_provider_combo"):
            return
        current = self.records_provider_combo.currentData()
        providers: list[str] = []
        for record in self._provider_records:
            label = _safe_text(record.get("provider_label"), "")
            if label and label not in providers:
                providers.append(label)
        with QSignalBlocker(self.records_provider_combo):
            self.records_provider_combo.clear()
            for provider in providers:
                self.records_provider_combo.addItem(provider, provider)
            index = self.records_provider_combo.findData(current)
            self.records_provider_combo.setCurrentIndex(index if index >= 0 else 0)

    def _rebuild_workspace_records(self) -> None:
        self._sync_provider_filter_options()
        cards = [self._build_cloud_card(record) for record in self._provider_records]
        cards.append(self._build_local_library_card(self._library_records))
        self._workspace_card_records = cards
        self._apply_workspace_filters()
        if hasattr(self, "_workspace"):
            self._workspace.set_records_summary_text(
                f"{ai_ui.AI_MANAGER_CLOUD_COUNT_TEMPLATE.format(count=len(self._provider_records))}  |  "
                f"{ai_ui.AI_MANAGER_LOCAL_COUNT_TEMPLATE.format(count=len(self._library_records))}"
            )

    def _card_matches_filters(self, card: RecordWorkspaceCardRecord) -> bool:
        payload = self._workspace_record_payload(card)
        kind = _safe_text(payload.get("kind"), "")
        raw = dict(payload.get("record") or {})
        type_filter = _safe_text(self.records_type_combo.currentData(), "all") if hasattr(self, "records_type_combo") else "all"
        provider_filter = _safe_text(self.records_provider_combo.currentData(), "all") if hasattr(self, "records_provider_combo") else "all"
        status_filter = _safe_text(self.records_status_combo.currentData(), "all") if hasattr(self, "records_status_combo") else "all"
        query = self.records_filter_input.text().strip().casefold() if hasattr(self, "records_filter_input") else ""

        filter_kind = "local" if kind in {"local", "local_library"} else kind
        if type_filter != "all" and filter_kind != type_filter:
            return False
        if provider_filter != "all" and _safe_text(raw.get("provider_label"), "") != provider_filter:
            return False
        if status_filter != "all" and _safe_text(payload.get("status_key"), "") != status_filter:
            return False
        if query:
            haystack = " ".join(
                [
                    card.title,
                    card.subtitle,
                    card.extra,
                    _safe_text(raw.get("label"), ""),
                    _safe_text(raw.get("repo_id"), ""),
                    _safe_text(raw.get("filename"), ""),
                    _safe_text(raw.get("default_model"), ""),
                ]
            ).casefold()
            if query not in haystack:
                return False
        return True

    def _apply_workspace_filters(self) -> None:
        if not hasattr(self, "records_list"):
            return
        visible = [card for card in self._workspace_card_records if self._card_matches_filters(card)]
        self.records_list.set_records(visible)

    def _reset_workspace_filters(self) -> None:
        if hasattr(self, "records_filter_input"):
            self.records_filter_input.clear()
        for widget_name in ("records_type_combo", "records_provider_combo", "records_status_combo"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                try:
                    widget.setCurrentIndex(0)
                except Exception:
                    pass
        self._apply_workspace_filters()

    def _activate_workspace_record(self, record) -> None:
        payload = self._workspace_record_payload(record)
        self._active_workspace_key = str(getattr(record, "recordKey", "") or "")
        self._active_workspace_payload = dict(payload)
        if payload.get("kind") == "cloud":
            self._provider_current_id = _safe_int(payload.get("id"), 0) or None
            self._set_provider_mode("edit")
            return
        if payload.get("kind") == "local_library":
            self._provider_current_id = None
            self._set_provider_mode("new")
            self._set_entry_kind("local")
            self.provider_status.setText("Yerel model indirme kataloğu hazır.")
            return
        if payload.get("kind") == "local":
            self._provider_current_id = None
            self._set_provider_mode("edit")
            return
            self.local_model_summary.setText(
                f"{_safe_text((payload.get('record') or {}).get('repo_id'))}\n"
                f"{_safe_text((payload.get('record') or {}).get('filename'))} | "
                f"{_safe_text((payload.get('record') or {}).get('size_text'))}"
            )
            self.provider_status.setText("Lokal model kaydı seçildi.")
            return

    def _clear_active_workspace_record(self) -> None:
        self._active_workspace_key = ""
        self._active_workspace_payload = {}
        self._provider_current_id = None
        if hasattr(self, "records_list"):
            self.records_list.clear_active_record()
        self._update_provider_buttons()

    def _selected_cloud_record_ids(self) -> list[int]:
        ids: list[int] = []
        if not hasattr(self, "records_list"):
            return ids
        for card in self.records_list.get_selected_records():
            payload = self._workspace_record_payload(card)
            if payload.get("kind") != "cloud":
                continue
            provider_id = _safe_int(payload.get("id"), 0)
            if provider_id > 0:
                ids.append(provider_id)
        return ids

    def _refresh_left_panel_header(self) -> None:
        if not hasattr(self, "left_panel_title"):
            return
        mode = str(self._provider_mode or "new").lower()
        if mode == "new":
            self.left_panel_title.setText("Yeni kaynak")
            self.left_panel_hint.setText("Cloud API hesabı bağla veya yerel model indir.")
            return
        if mode == "bulk":
            self.left_panel_title.setText(ai_ui.AI_MANAGER_LEFT_BULK_TITLE)
            self.left_panel_hint.setText(ai_ui.AI_MANAGER_LEFT_BULK_HINT)
            return
        self.left_panel_title.setText(ai_ui.AI_MANAGER_LEFT_EDIT_TITLE)
        if self._active_workspace_payload.get("kind") == "cloud":
            record = dict(self._active_workspace_payload.get("record") or {})
            self.left_panel_hint.setText(f"Seçili cloud hesap: {_safe_text(record.get('label'), '-')}")
            return
        if self._active_workspace_payload.get("kind") == "local":
            record = dict(self._active_workspace_payload.get("record") or {})
            self.left_panel_hint.setText(f"Seçili lokal model: {_safe_text(record.get('repo_id'), '-')}")
            return
        self.left_panel_hint.setText(ai_ui.AI_MANAGER_LEFT_EDIT_HINT)

    def _sort_search_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mode = str(self.sort_combo.currentData() or "best")
        if mode == "downloads":
            return sorted(records, key=lambda row: _safe_int(row.get("downloads")), reverse=True)
        if mode == "likes":
            return sorted(records, key=lambda row: _safe_int(row.get("likes")), reverse=True)
        return list(records)

    def _rebuild_results_list(self) -> None:
        current_repo = _safe_text(self._selected_detail.get("repo_id"), "")
        records = self._sort_search_records(self._search_records)
        self.results_list.clear()

        for record in records:
            repo_id = _safe_text(record.get("repo_id"), "")
            downloads = _safe_int(record.get("downloads"))
            likes = _safe_int(record.get("likes"))
            summary = _safe_text(record.get("description"), "")
            item = QListWidgetItem(f"{repo_id}\nDownloads: {downloads} | Likes: {likes}\n{summary}")
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.results_list.addItem(item)
            if repo_id and repo_id == current_repo:
                self.results_list.setCurrentItem(item)

        if self.results_list.count() > 0 and self.results_list.currentRow() < 0:
            self.results_list.setCurrentRow(0)
        if self.results_list.count() <= 0:
            self._clear_detail()

        self.results_status.setText(ai_ui.AI_MANAGER_TOTAL_RESULTS_TEMPLATE.format(count=self.results_list.count()))

    def _start_search(self, *, initial: bool = False) -> None:
        if self._search_worker is not None and self._search_worker.isRunning():
            return

        query = self.search_input.text().strip()
        if initial and not query:
            query = "gguf"
        if query:
            self.search_input.setText(query)

        self.results_status.setText(ai_ui.AI_MANAGER_SEARCHING_TEXT)
        self._search_status.setText(ai_ui.AI_MANAGER_HF_SCANNING_TEXT)
        self.btn_search.setEnabled(False)

        self._search_worker = SyncWorker(
            ai_actions.action_search_hf_models,
            query,
            parent=self,
            limit=int((self._settings or {}).get("search_limit") or 16),
        )

        def _done(result: Result) -> None:
            self.btn_search.setEnabled(True)
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self.results_status.setText(ai_ui.AI_MANAGER_SEARCH_FAILED_TEXT)
                self._search_status.setText(ai_ui.AI_MANAGER_SEARCH_ERROR_TEXT)
                return

            self._search_records = list((result.data or {}).get("records") or [])
            self._rebuild_results_list()
            self._search_status.setText(ai_ui.AI_MANAGER_SEARCH_COMPLETE_TEXT)

        def _finished() -> None:
            self.btn_search.setEnabled(True)
            self._search_worker = None

        self._search_worker.result_ready.connect(_done)
        self._search_worker.finished.connect(_finished)
        self._search_worker.start()

    def _derive_capabilities(self, detail: dict[str, Any]) -> list[str]:
        tags = [str(tag or "").strip().lower() for tag in list(detail.get("tags") or [])]
        capabilities: list[str] = []
        if any("vision" in tag for tag in tags):
            capabilities.append("Vision")
        if any("tool" in tag for tag in tags):
            capabilities.append("Tool Use")
        if any("reason" in tag for tag in tags):
            capabilities.append("Reasoning")
        if any("gguf" in tag for tag in tags):
            capabilities.append("GGUF")
        pipeline_tag = str(detail.get("pipeline_tag") or "").strip()
        if pipeline_tag and pipeline_tag not in capabilities:
            capabilities.append(pipeline_tag)
        return capabilities[:6]

    def _on_result_selected(self) -> None:
        item = self.results_list.currentItem()
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return
        repo_id = _safe_text(payload.get("repo_id"), "")
        if repo_id:
            self._load_detail(repo_id)

    def _load_detail(self, repo_id: str) -> None:
        if self._detail_worker is not None and self._detail_worker.isRunning():
            return

        self.download_stage.setText(ai_ui.AI_MANAGER_MODEL_DETAIL_LOADING_TEXT)
        self.btn_download.setEnabled(False)
        self.btn_open_model_page.setEnabled(False)
        self._detail_worker = SyncWorker(ai_actions.action_get_hf_model_details, repo_id, parent=self)

        def _done(result: Result) -> None:
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self.download_stage.setText(ai_ui.AI_MANAGER_MODEL_DETAIL_FAILED_TEXT)
                self._clear_detail()
                return

            detail = dict((result.data or {}).get("detail") or {})
            self._selected_detail = detail
            repo_text = _safe_text(detail.get("repo_id"))
            desc_text = _safe_text(detail.get("description"), ai_ui.AI_MANAGER_DETAIL_NO_DESCRIPTION_TEXT)
            files = list(detail.get("files") or [])
            capabilities = ", ".join(self._derive_capabilities(detail)) or ai_ui.AI_MANAGER_DETAIL_NO_CAPABILITY_TEXT
            self.local_model_summary.setText(
                ai_ui.AI_MANAGER_DETAIL_SUMMARY_TEMPLATE.format(
                    repo_id=repo_text,
                    downloads=_safe_int(detail.get("downloads")),
                    likes=_safe_int(detail.get("likes")),
                    capabilities=capabilities,
                    description=desc_text,
                )
            )

            self.file_combo.clear()
            for file_row in files:
                label = (
                    f"{_safe_text(file_row.get('format'))}  "
                    f"{_safe_text(file_row.get('quantization'))}  "
                    f"{_safe_text(file_row.get('size_text'))}  "
                    f"{_safe_text(file_row.get('filename'))}"
                )
                self.file_combo.addItem(label, file_row)

            has_files = self.file_combo.count() > 0
            self.btn_download.setEnabled(has_files)
            self.btn_open_model_page.setEnabled(bool(repo_text))
            self.download_stage.setText(
                ai_ui.AI_MANAGER_MODEL_READY_TEXT if has_files else ai_ui.AI_MANAGER_NO_DOWNLOADABLE_FILE_TEXT
            )

        def _finished() -> None:
            self._detail_worker = None

        self._detail_worker.result_ready.connect(_done)
        self._detail_worker.finished.connect(_finished)
        self._detail_worker.start()

    def _clear_detail(self) -> None:
        self._selected_detail = {}
        self.local_model_summary.setText(ai_ui.AI_MANAGER_MODEL_SUMMARY_EMPTY_TEXT)
        self.file_combo.clear()
        self.btn_download.setEnabled(False)
        self.btn_open_model_page.setEnabled(False)
        self.download_progress.setValue(0)

    def _refresh_library(self) -> None:
        if self._library_worker is not None and self._library_worker.isRunning():
            return

        self.library_status.setText(ai_ui.AI_MANAGER_LIBRARY_REFRESHING_TEXT)
        self._library_worker = SyncWorker(ai_actions.action_list_installed_models, parent=self)

        def _done(result: Result) -> None:
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self.library_status.setText(ai_ui.AI_MANAGER_LIBRARY_LOAD_FAILED_TEXT)
                return
            records = list((result.data or {}).get("records") or [])
            self._fill_library_table(records)
            self.library_status.setText(ai_ui.AI_MANAGER_LIBRARY_COUNT_TEMPLATE.format(count=len(records)))
            self.asset_local_count_pill.setText(ai_ui.AI_MANAGER_LOCAL_COUNT_TEMPLATE.format(count=len(records)))

        def _finished() -> None:
            self._library_worker = None

        self._library_worker.result_ready.connect(_done)
        self._library_worker.finished.connect(_finished)
        self._library_worker.start()

    def _fill_library_table(self, records: list[dict[str, Any]]) -> None:
        self._library_records = list(records or [])
        self._fill_installed_local_list(self._library_records)
        if not hasattr(self, "library_table"):
            self._rebuild_workspace_records()
            return
        with optimized_table_updates(self.library_table, len(records)):
            for row_index, record in enumerate(records):
                row_values = [
                    _safe_text(record.get("repo_id")),
                    _safe_text(record.get("filename")),
                    _safe_text(record.get("file_format")),
                    _safe_text(record.get("quantization")),
                    _safe_text(record.get("size_text")),
                    ai_ui.AI_MANAGER_LIBRARY_READY_TEXT if bool(record.get("exists_on_disk")) else ai_ui.AI_MANAGER_LIBRARY_MISSING_TEXT,
                ]
                for col_index, value in enumerate(row_values):
                    item = QTableWidgetItem(value)
                    if col_index == 0:
                        item.setData(Qt.ItemDataRole.UserRole, record)
                    self.library_table.setItem(row_index, col_index, item)

    def _fill_installed_local_list(self, records: list[dict[str, Any]]) -> None:
        if not hasattr(self, "installed_local_list"):
            return
        self.installed_local_list.clear()
        for record in records:
            payload = dict(record or {})
            item = QListWidgetItem(
                f"{_safe_text(payload.get('repo_id'), '-')}\n"
                f"{_safe_text(payload.get('filename'), '-')} · {_safe_text(payload.get('size_text'), '-')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, payload)
            self.installed_local_list.addItem(item)
        self._update_local_delete_button()

    def _selected_installed_local_record(self) -> dict[str, Any] | None:
        if not hasattr(self, "installed_local_list"):
            return None
        item = self.installed_local_list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return dict(payload) if isinstance(payload, dict) else None

    def _update_local_delete_button(self) -> None:
        if hasattr(self, "btn_delete_local_model"):
            self.btn_delete_local_model.setEnabled(
                self._selected_installed_local_record() is not None
            )

    def _delete_selected_local_model(self) -> None:
        record = self._selected_installed_local_record()
        model_id = _safe_int((record or {}).get("id"), 0)
        if model_id <= 0:
            AppMessageCenter.warning(self, "AI", "Silmek için yüklü bir yerel model seçin.")
            return
        label = _safe_text((record or {}).get("repo_id"), "yerel model")
        if not AppMessageCenter.confirm(
            self,
            "Yerel modeli sil",
            f"{label} dosyası ve Model Hub kaydı silinsin mi?",
            default_yes=False,
        ):
            return
        result = ai_actions.action_delete_installed_model(model_id)
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            self.download_stage.setText(result.message)
            return
        self.download_stage.setText(result.message)
        self._refresh_library()

    def _fill_cloud_accounts_table(self, records: list[dict[str, Any]]) -> None:
        self._provider_records = list(records or [])
        if not hasattr(self, "cloud_accounts_table"):
            self._rebuild_workspace_records()
            return
        with optimized_table_updates(self.cloud_accounts_table, len(records)):
            for row_index, record in enumerate(records):
                row_values = [
                    _safe_text(record.get("label")),
                    _safe_text(record.get("provider_label")),
                    _safe_text(record.get("default_model")),
                    ai_ui.AI_MANAGER_ENABLED_TEXT if bool(record.get("is_enabled")) else ai_ui.AI_MANAGER_DISABLED_TEXT,
                ]
                for col_index, value in enumerate(row_values):
                    item = QTableWidgetItem(value)
                    self.cloud_accounts_table.setItem(row_index, col_index, item)

    def _on_choose_root(self) -> None:
        if self._save_settings_worker is not None and self._save_settings_worker.isRunning():
            return
        current_dir = _safe_text(self._settings.get("download_root"), str(Path.home()))
        picked = QFileDialog.getExistingDirectory(self, ai_ui.AI_MANAGER_PICK_MODEL_FOLDER_TITLE, current_dir)
        if not picked:
            return

        self._save_settings_worker = SyncWorker(ai_actions.action_set_ai_download_root, picked, parent=self)
        self.download_root_value.setText(ai_ui.AI_MANAGER_DOWNLOAD_ROOT_SAVING_TEXT)

        def _done(result: Result) -> None:
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self.download_root_value.setText(ai_ui.AI_MANAGER_DOWNLOAD_ROOT_SAVE_FAILED_TEXT)
                return
            self._settings = dict((result.data or {}).get("settings") or {})
            self.download_root_value.setText(_safe_text(self._settings.get("download_root"), "-"))
            self._set_header_status(ai_ui.AI_MANAGER_DOWNLOAD_ROOT_UPDATED_TEXT)

        def _finished() -> None:
            self._save_settings_worker = None

        self._save_settings_worker.result_ready.connect(_done)
        self._save_settings_worker.finished.connect(_finished)
        self._save_settings_worker.start()

    def _open_current_root(self) -> None:
        target = _safe_text(self._settings.get("download_root"), "")
        if not target or target == "-":
            AppMessageCenter.warning(self, "AI", ai_ui.AI_MANAGER_FOLDER_NOT_SELECTED_TEXT)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _open_model_page(self) -> None:
        repo_id = _safe_text(self._selected_detail.get("repo_id"), "")
        if repo_id:
            QDesktopServices.openUrl(QUrl(f"https://huggingface.co/{repo_id}"))

    def _start_download(self) -> None:
        if self._download_worker is not None and self._download_worker.isRunning():
            return

        repo_id = _safe_text(self._selected_detail.get("repo_id"), "")
        file_payload = self.file_combo.currentData()
        filename = _safe_text(file_payload.get("filename"), "") if isinstance(file_payload, dict) else ""
        root = _safe_text(self._settings.get("download_root"), "")
        if not repo_id or not filename or not root or root == "-":
            AppMessageCenter.warning(self, "AI", ai_ui.AI_MANAGER_PICK_ROOT_AND_FILE_TEXT)
            return

        self.btn_download.setEnabled(False)
        self.btn_pause_download.setEnabled(True)
        self.btn_pause_download.show()
        self.download_progress.setValue(0)
        self.download_stage.setText(ai_ui.AI_MANAGER_DOWNLOADING_TEMPLATE.format(repo_id=repo_id))
        self._download_worker = _AiDownloadWorker(repo_id=repo_id, filename=filename, download_root=root, parent=self)

        def _progress(percent: int, label: str) -> None:
            self.download_progress.setValue(max(0, min(100, int(percent or 0))))
            self.download_stage.setText(_safe_text(label, ai_ui.AI_MANAGER_DOWNLOADING_TEXT))

        def _done(result: Result) -> None:
            self.btn_download.setEnabled(True)
            self.btn_pause_download.setEnabled(False)
            data = dict(result.data or {}) if isinstance(result.data, dict) else {}
            if not result.success:
                self.download_stage.setText(ai_ui.AI_MANAGER_DOWNLOAD_FAILED_TEXT)
                MessageHandler.show(self, result, only_errors=True)
                return
            if bool(data.get("paused")):
                self.download_stage.setText(result.message or "İndirme duraklatıldı; devam etmeye hazır.")
                self.btn_download.setText("İndirmeye devam et")
                return
            self.download_progress.setValue(100)
            self.download_stage.setText(result.message or ai_ui.AI_MANAGER_DOWNLOAD_DONE_TEXT)
            self.btn_download.setText(ai_ui.AI_MANAGER_DOWNLOAD_AND_SAVE_TEXT)
            MessageHandler.show(self, result, only_errors=False)
            self._refresh_library()

        def _finished() -> None:
            self.btn_download.setEnabled(self.file_combo.count() > 0)
            self.btn_pause_download.setEnabled(False)
            self.btn_pause_download.hide()
            self._download_worker = None

        self._download_worker.progress_changed.connect(_progress)
        self._download_worker.result_ready.connect(_done)
        self._download_worker.finished.connect(_finished)
        self._download_worker.start()

    def _pause_download(self) -> None:
        worker = self._download_worker
        if worker is None or not worker.isRunning():
            return
        worker.request_pause()
        self.btn_pause_download.setEnabled(False)
        self.download_stage.setText("İndirme güvenli noktada duraklatılıyor...")

    def _selected_library_record(self) -> dict[str, Any] | None:
        if not hasattr(self, "library_table"):
            if self._active_workspace_payload.get("kind") == "local":
                record = self._active_workspace_payload.get("record")
                return record if isinstance(record, dict) else None
            if hasattr(self, "records_list"):
                for card in self.records_list.get_selected_records():
                    payload = self._workspace_record_payload(card)
                    if payload.get("kind") == "local":
                        record = payload.get("record")
                        return record if isinstance(record, dict) else None
            return None
        row = self.library_table.currentRow()
        if row < 0:
            return None
        item = self.library_table.item(row, 0)
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        return payload if isinstance(payload, dict) else None

    def _open_selected_library_folder(self) -> None:
        record = self._selected_library_record()
        if not record:
            AppMessageCenter.warning(self, "AI", ai_ui.AI_MANAGER_PICK_LIBRARY_MODEL_TEXT)
            return
        local_path = _safe_text(record.get("local_path"), "")
        if not local_path or local_path == "-":
            AppMessageCenter.warning(self, "AI", ai_ui.AI_MANAGER_LIBRARY_PATH_MISSING_TEXT)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(local_path).parent)))

    def _on_provider_sidebar_toggled(self, panel_id: str, active: bool) -> None:
        if not active:
            self._provider_sidebar.set_active_panel(self._provider_mode)
            return
        self._set_provider_mode(panel_id)

    def _provider_item_text(self, record: dict[str, Any]) -> str:
        status = ai_ui.AI_MANAGER_ENABLED_TEXT if bool(record.get("is_enabled")) else ai_ui.AI_MANAGER_DISABLED_TEXT
        model_hint = _safe_text(record.get("default_model"), ai_ui.AI_MANAGER_PROVIDER_MODEL_MISSING_TEXT)
        masked_key = _safe_text(record.get("api_key_masked"), "-")
        return (
            f"{_safe_text(record.get('label'))}\n"
            f"{_safe_text(record.get('provider_label'))} | {status}\n"
            f"{masked_key} | {model_hint}"
        )

    def _load_provider_accounts(self, *, selected_id: int | None = None) -> None:
        result = ai_actions.action_list_provider_accounts()
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            self.provider_status.setText(ai_ui.AI_MANAGER_PROVIDER_LOAD_FAILED_TEXT)
            return

        current_selection = selected_id if selected_id is not None else self._provider_current_id
        records = list((result.data or {}).get("records") or [])
        self.provider_list.clear()
        for record in records:
            item = QListWidgetItem(self._provider_item_text(record))
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.provider_list.addItem(item)
            if current_selection and int(record.get("id") or 0) == int(current_selection):
                item.setSelected(True)
                self.provider_list.setCurrentItem(item)

        self._fill_cloud_accounts_table(records)
        self.provider_count_pill.setText(ai_ui.AI_MANAGER_PROVIDER_COUNT_TEMPLATE.format(count=len(records)))
        self.asset_cloud_count_pill.setText(ai_ui.AI_MANAGER_CLOUD_COUNT_TEMPLATE.format(count=len(records)))
        self.cloud_accounts_status.setText(ai_ui.AI_MANAGER_CLOUD_STATUS_TEMPLATE.format(count=len(records)))
        self.provider_status.setText(
            ai_ui.AI_MANAGER_PROVIDER_READY_TEXT if records else ai_ui.AI_MANAGER_PROVIDER_EMPTY_TEXT
        )

        if self._provider_mode == "edit" and self.provider_list.count() > 0 and self.provider_list.currentRow() < 0:
            self.provider_list.setCurrentRow(0)
        if self._provider_mode == "bulk":
            self._update_bulk_panel_state()
        self._update_provider_buttons()

    def _selected_provider_ids(self) -> list[int]:
        workspace_ids = self._selected_cloud_record_ids()
        if workspace_ids:
            return workspace_ids
        ids: list[int] = []
        for item in self.provider_list.selectedItems():
            payload = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict):
                provider_id = _safe_int(payload.get("id"), 0)
                if provider_id > 0:
                    ids.append(provider_id)
        return ids

    def _selected_single_provider_id(self) -> Optional[int]:
        if self._provider_current_id:
            return int(self._provider_current_id)
        ids = self._selected_provider_ids()
        return ids[0] if len(ids) == 1 else None

    def _reset_provider_form(self) -> None:
        self._provider_current_id = None
        default_spec = self._default_provider_spec()
        with QSignalBlocker(self.provider_type_combo):
            self.provider_type_combo.setCurrentIndex(0)
        self.provider_label_input.clear()
        self.provider_endpoint_input.setText(default_spec.get("endpoint", ""))
        self.provider_model_input.clear()
        self._fill_provider_model_combo([], selected_model="")
        self.provider_key_input.clear()
        self._clear_provider_validation()
        self.provider_enabled_combo.setCurrentIndex(0)
        self._sync_provider_reasoning_control(selected_effort="auto")
        self._update_provider_buttons()

    def _clear_provider_validation(self, *_args) -> None:
        if hasattr(self, "provider_validation_label"):
            self.provider_validation_label.clear()
            self.provider_validation_label.hide()
        for widget in (
            getattr(self, "provider_label_input", None),
            getattr(self, "provider_key_input", None),
        ):
            if widget is None:
                continue
            widget.setProperty("validationError", False)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _validate_provider_form(self) -> bool:
        missing: list[tuple[QLineEdit, str]] = []
        if not self.provider_label_input.text().strip():
            missing.append((self.provider_label_input, "Bağlantı adı"))
        if not self.provider_key_input.text().strip():
            missing.append((self.provider_key_input, "API anahtarı"))
        if not self._current_provider_code():
            self.provider_validation_label.setText("Provider seçimi zorunludur.")
            self.provider_validation_label.show()
            return False
        if not missing:
            self._clear_provider_validation()
            return True
        for widget, _label in missing:
            widget.setProperty("validationError", True)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.provider_validation_label.setText(
            "Eksik alanlar: " + ", ".join(label for _widget, label in missing) + "."
        )
        self.provider_validation_label.show()
        missing[0][0].setFocus()
        return False

    def _on_provider_type_changed(self) -> None:
        if not hasattr(self, "provider_endpoint_input") or self.provider_endpoint_input is None:
            return
        spec = self.provider_type_combo.currentData()
        if isinstance(spec, dict) and (self._provider_mode == "new" or not self.provider_endpoint_input.text().strip()):
            self.provider_endpoint_input.setText(str(spec.get("endpoint") or "").strip())
        self._sync_provider_reasoning_control()

    def _current_provider_code(self) -> str:
        spec = self.provider_type_combo.currentData()
        return str(spec.get("code") or "").strip() if isinstance(spec, dict) else ""

    def _on_provider_model_selected(self) -> None:
        payload = self.provider_model_combo.currentData()
        model_id = _safe_text(payload.get("id"), "") if isinstance(payload, dict) else _safe_text(payload, "")
        if model_id:
            self.provider_model_input.setText(model_id)
        self._sync_provider_reasoning_control(
            dict(payload.get("reasoning_capabilities") or {}) if isinstance(payload, dict) else None,
        )

    def _sync_provider_reasoning_control(
        self,
        capabilities: dict[str, Any] | None = None,
        *,
        selected_effort: str | None = None,
    ) -> None:
        if not hasattr(self, "provider_reasoning_combo"):
            return
        payload = self.provider_model_combo.currentData()
        model_metadata = dict(payload or {}) if isinstance(payload, dict) else {}
        resolved = dict(capabilities or {})
        if not resolved:
            resolved = provider_reasoning_capabilities(
                self._current_provider_code(),
                self.provider_model_input.text().strip(),
                model_metadata=model_metadata,
            )
        labels = {
            "auto": "Otomatik",
            "off": "Kapali",
            "low": "Dusuk",
            "medium": "Orta",
            "high": "Yuksek",
        }
        current = _safe_text(
            selected_effort if selected_effort is not None else self.provider_reasoning_combo.currentData(),
            "auto",
        ).casefold()
        efforts = list(resolved.get("efforts") or ["auto"])
        with QSignalBlocker(self.provider_reasoning_combo):
            self.provider_reasoning_combo.clear()
            for effort in efforts:
                self.provider_reasoning_combo.addItem(labels.get(effort, effort), effort)
            index = self.provider_reasoning_combo.findData(current)
            self.provider_reasoning_combo.setCurrentIndex(index if index >= 0 else 0)
        supported = bool(resolved.get("supported"))
        self.provider_reasoning_combo.setEnabled(supported)
        control = _safe_text(resolved.get("control"), "")
        self.provider_reasoning_status.setText(
            f"Model reasoning destekliyor; kontrol: {control}."
            if supported
            else "Secili model ayarlanabilir thinking/reasoning effort sunmuyor."
        )

    def _provider_model_label(self, record: dict[str, Any]) -> str:
        price = _safe_text(record.get("pricing_label"), "priced")
        context = _safe_int(record.get("context_length"), 0)
        context_text = f" | ctx {context}" if context > 0 else ""
        return f"{_safe_text(record.get('id'))} | {price}{context_text}"

    def _fill_provider_model_combo(
        self,
        records: list[dict[str, Any]],
        *,
        selected_model: str | None = None,
        preserve_selected: bool = True,
    ) -> None:
        selected = _safe_text(selected_model if selected_model is not None else self.provider_model_input.text(), "")
        record_ids = {_safe_text(record.get("id"), "") for record in records}
        if selected and not preserve_selected and record_ids and selected not in record_ids:
            selected = ""
        with QSignalBlocker(self.provider_model_combo):
            self.provider_model_combo.clear()
            if selected:
                self.provider_model_combo.addItem(f"{selected} | mevcut", {"id": selected})
            for record in records:
                model_id = _safe_text(record.get("id"), "")
                if not model_id or model_id == selected:
                    continue
                self.provider_model_combo.addItem(self._provider_model_label(record), dict(record))
            if selected:
                self.provider_model_combo.setCurrentIndex(0)
        if not selected and self.provider_model_combo.count() > 0:
            self._on_provider_model_selected()
        total = len(records)
        free_total = sum(1 for record in records if bool(record.get("is_free")))
        if total:
            self.provider_models_status.setText(f"{total} model listelendi; {free_total} ucretsiz.")
        else:
            self.provider_models_status.setText("Provider modeli manuel yazilabilir veya listeden secilebilir.")

    def _load_provider_models(self) -> None:
        if self._provider_models_worker is not None and self._provider_models_worker.isRunning():
            return
        provider_code = self._current_provider_code()
        endpoint_url = self.provider_endpoint_input.text().strip()
        api_key = self.provider_key_input.text().strip()
        free_only = self.provider_free_only_checkbox.isChecked()
        self.provider_models_status.setText("Provider modelleri aliniyor...")
        self.btn_load_provider_models.setEnabled(False)
        self._provider_models_worker = SyncWorker(
            ai_actions.action_list_provider_models,
            parent=self,
            provider_code=provider_code,
            endpoint_url=endpoint_url,
            api_key=api_key,
            free_only=free_only,
            limit=200,
        )

        def _done(result: Result) -> None:
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self.provider_models_status.setText("Provider modelleri alinamadi.")
                return
            data = result.data or {}
            records = [dict(row) for row in (data.get("records") or []) if isinstance(row, dict)]
            self._fill_provider_model_combo(records, preserve_selected=not free_only)
            self.provider_models_status.setText(
                f"{len(records)} model listelendi; {(data.get('free_total') or 0)} ucretsiz. Secim varsayilan model alanina yazilir."
            )

        def _finished() -> None:
            self.btn_load_provider_models.setEnabled(True)
            self._provider_models_worker = None

        self._provider_models_worker.result_ready.connect(_done)
        self._provider_models_worker.finished.connect(_finished)
        self._provider_models_worker.start()

    def _on_provider_selection_changed(self) -> None:
        if self._provider_mode == "edit":
            self._load_selected_provider_into_form()
        elif self._provider_mode == "bulk":
            self._update_bulk_panel_state()
        self._update_provider_buttons()

    def _load_selected_provider_into_form(self) -> None:
        provider_id = self._selected_single_provider_id()
        if provider_id is None:
            if self._provider_mode == "edit":
                self.provider_status.setText(ai_ui.AI_MANAGER_SELECT_SINGLE_PROVIDER_TEXT)
            self._provider_current_id = None
            self._update_provider_buttons()
            return

        result = ai_actions.action_get_provider_account(provider_id)
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            self.provider_status.setText(ai_ui.AI_MANAGER_PROVIDER_DETAIL_FAILED_TEXT)
            return

        record = dict((result.data or {}).get("record") or {})
        self._provider_current_id = int(record.get("id") or 0)
        spec = self._provider_spec_for_code(_safe_text(record.get("provider_code"), ""))
        combo_index = self.provider_type_combo.findData(spec)
        with QSignalBlocker(self.provider_type_combo):
            self.provider_type_combo.setCurrentIndex(combo_index if combo_index >= 0 else 0)
        self.provider_label_input.setText(_safe_text(record.get("label"), ""))
        self.provider_endpoint_input.setText(_safe_text(record.get("endpoint_url"), ""))
        self.provider_model_input.setText(_safe_text(record.get("default_model"), ""))
        self._fill_provider_model_combo([], selected_model=_safe_text(record.get("default_model"), ""))
        self._sync_provider_reasoning_control(
            dict(record.get("reasoning_capabilities") or {}),
            selected_effort=_safe_text(record.get("reasoning_effort"), "auto"),
        )
        self.provider_key_input.setText(_safe_text(record.get("api_key"), ""))
        self.provider_enabled_combo.setCurrentIndex(0 if bool(record.get("is_enabled")) else 1)
        self.provider_status.setText(
            ai_ui.AI_MANAGER_EDITING_PROVIDER_TEMPLATE.format(label=_safe_text(record.get("label"), "-"))
        )
        self._update_provider_buttons()

    def _save_provider_account(self) -> None:
        if not self._validate_provider_form():
            return
        spec = self.provider_type_combo.currentData()
        provider_code = str(spec.get("code") or "").strip() if isinstance(spec, dict) else ""
        result = ai_actions.action_save_provider_account(
            provider_code=provider_code,
            label=self.provider_label_input.text().strip(),
            api_key=self.provider_key_input.text().strip(),
            provider_id=self._provider_current_id if self._provider_mode == "edit" else None,
            endpoint_url=self.provider_endpoint_input.text().strip(),
            default_model=self.provider_model_input.text().strip(),
            is_enabled=bool(self.provider_enabled_combo.currentData()),
        )
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            self.provider_status.setText(ai_ui.AI_MANAGER_PROVIDER_SAVE_FAILED_TEXT)
            return

        record = dict((result.data or {}).get("record") or {})
        self._provider_current_id = int(record.get("id") or 0)
        self.provider_status.setText(
            ai_ui.AI_MANAGER_PROVIDER_SAVED_TEMPLATE.format(label=_safe_text(record.get("label"), "-"))
        )
        selected_id = self._provider_current_id
        self._load_provider_accounts(selected_id=selected_id)
        if self._provider_mode == "new":
            self._reset_provider_form()

    def _delete_current_provider(self) -> None:
        provider_id = self._provider_current_id or self._selected_single_provider_id()
        if provider_id is None:
            AppMessageCenter.warning(self, "AI", ai_ui.AI_MANAGER_PICK_PROVIDER_TO_DELETE_TEXT)
            return

        answer = AppMessageCenter.confirm(
            self,
            ai_ui.AI_MANAGER_DELETE_PROVIDER_TITLE,
            ai_ui.AI_MANAGER_DELETE_PROVIDER_CONFIRM_TEXT,
            default_yes=False,
        )
        if not answer:
            return

        result = ai_actions.action_delete_provider_accounts([provider_id])
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            self.provider_status.setText(ai_ui.AI_MANAGER_PROVIDER_DELETE_FAILED_TEXT)
            return

        self.provider_status.setText(ai_ui.AI_MANAGER_PROVIDER_DELETED_TEXT)
        self._provider_current_id = None
        self._load_provider_accounts()
        if self._provider_mode == "edit":
            self._reset_provider_form()

    def _delete_bulk_selected(self) -> None:
        ids = self._selected_provider_ids()
        if not ids:
            AppMessageCenter.warning(self, "AI", ai_ui.AI_MANAGER_PICK_PROVIDER_TO_BULK_DELETE_TEXT)
            return

        answer = AppMessageCenter.confirm(
            self,
            ai_ui.AI_MANAGER_BULK_DELETE_TITLE,
            ai_ui.AI_MANAGER_BULK_DELETE_CONFIRM_TEMPLATE.format(count=len(ids)),
            default_yes=False,
        )
        if not answer:
            return

        result = ai_actions.action_delete_provider_accounts(ids)
        if not result.success:
            MessageHandler.show(self, result, only_errors=True)
            self.provider_status.setText(ai_ui.AI_MANAGER_BULK_DELETE_FAILED_TEXT)
            return

        self.provider_status.setText(ai_ui.AI_MANAGER_BULK_DELETED_TEMPLATE.format(count=len(ids)))
        self._load_provider_accounts()
        self._update_bulk_panel_state()

    def _clear_provider_selection(self) -> None:
        self.provider_list.clearSelection()
        if hasattr(self, "records_list"):
            self.records_list.clear_selected_records()
        self._provider_current_id = None
        self._update_bulk_panel_state()
        self._update_provider_buttons()

    def _open_selected_provider_for_edit(self) -> None:
        if self.provider_list.count() > 0:
            self._set_provider_mode("edit")

    def _update_bulk_panel_state(self) -> None:
        count = len(self._selected_provider_ids())
        self.bulk_summary.setText(ai_ui.AI_MANAGER_BULK_SUMMARY_TEMPLATE.format(count=count))
        self.btn_bulk_delete.setEnabled(count > 0)

    def closeEvent(self, event) -> None:
        """Shut down Hub workers before Qt deletes their receiver widgets."""

        self._is_disposing = True
        for worker in (
            self._search_worker,
            self._detail_worker,
            self._settings_worker,
            self._save_settings_worker,
            self._library_worker,
            self._provider_models_worker,
            self._download_worker,
        ):
            self._shutdown_worker(worker)
        self._search_worker = None
        self._detail_worker = None
        self._settings_worker = None
        self._save_settings_worker = None
        self._library_worker = None
        self._provider_models_worker = None
        self._download_worker = None
        super().closeEvent(event)

    @staticmethod
    def _shutdown_worker(worker: SyncWorker | _AiDownloadWorker | None) -> None:
        if worker is None:
            return
        for signal_name in (
            "result_ready",
            "progress",
            "progress_changed",
            "stage_changed",
            "finished",
        ):
            signal = getattr(worker, signal_name, None)
            if signal is None or not hasattr(signal, "disconnect"):
                continue
            try:
                signal.disconnect()
            except Exception:
                pass
        try:
            request_pause = getattr(worker, "request_pause", None)
            if callable(request_pause):
                request_pause()
            worker.requestInterruption()
        except Exception:
            pass
        try:
            if worker.isRunning():
                worker.wait()
        except Exception:
            pass

    def _update_provider_buttons(self) -> None:
        if self._provider_mode == "bulk":
            self.btn_bulk_delete.setEnabled(len(self._selected_provider_ids()) > 0)
            return
        if getattr(self, "_entry_kind", "cloud") == "local":
            self.btn_save_provider.setEnabled(False)
            self.btn_delete_provider.setEnabled(False)
            self.btn_save_provider.setText("İndirme panelini kullan")
            return
        if self._provider_mode == "edit":
            can_edit = self._provider_current_id is not None
            self.btn_save_provider.setText("Bağlantıyı doğrula ve kaydet")
            self.btn_save_provider.setEnabled(can_edit)
            self.btn_delete_provider.setEnabled(can_edit)
        else:
            self.btn_save_provider.setText("Bağlantıyı doğrula ve kaydet")
            self.btn_save_provider.setEnabled(True)
            self.btn_delete_provider.setEnabled(False)

