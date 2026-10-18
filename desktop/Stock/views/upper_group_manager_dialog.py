from __future__ import annotations

from typing import Any, Optional

from .views import *
from .company_manager_dialog import ManagerCardsListWidget, StockManagerWorkspaceBehaviorAdapter


class UpperGroupManagerDialog(FullscreenDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Üst Gruplar")
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
            left_subtitle="Düzenlemek için sağdaki listeden bir üst grup seç.",
            filters_title=STOCK_MANAGER_FILTERS_TITLE,
            records_title="Üst Grup Listesi",
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
            style_sheet=compose_record_workspace_style(),
            shell_kwargs=STOCK_MANAGER_WORKSPACE_SHELL_KWARGS,
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": "Yeni üst grup paneli",
                    "icon_path": str(ASSETS_DIR / "yeni-kayit.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": "Üst grup düzenleme paneli",
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
        splitter = self._workspace_shell.splitter
        splitter.setChildrenCollapsible(True)
        splitter.setHandleWidth(6)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        self._manager_splitter = splitter
        self._left_stick_size = 520
        self.left_panel_title = self._workspace.left_card.title_label
        self.left_panel_hint = self._workspace.left_card.subtitle_label
        self._editor_scroll = self._workspace.editor_scroll
        self._editor_actions_wrap = self._workspace.editor_actions_host
        self._editor_host = QWidget(self._workspace.editor_host)
        self._editor_host.setObjectName("FormBody")
        editor_layout = QVBoxLayout(self._editor_host)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(10)
        self.bulk_panel = self._workspace.bulk_panel

        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self.le_pk = QLineEdit()
        self.le_pk.setEnabled(False)
        self.le_pk.hide()
        self.le_name = QLineEdit()
        self.le_name.setPlaceholderText("Üst grup adı")
        form.addRow("Üst Grup", self.le_name)
        editor_layout.addLayout(form)

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text=STOCK_MANAGER_CLEAR_TEXT,
            save_new_text="Üst Grup Kaydet",
            save_edit_text=STOCK_MANAGER_SAVE_EDIT_TEXT,
            delete_text=STOCK_MANAGER_DELETE_TEXT,
        )
        self.btn_clear = self._workspace.editor_action_bar.clear_button
        self.btn_save = self._workspace.editor_action_bar.save_button
        self.btn_delete = self._workspace.editor_action_bar.delete_button
        self._workspace.editor_action_bar.clearRequested.connect(self.clear_form)
        self._workspace.editor_action_bar.saveRequested.connect(self.save_or_update)
        self._workspace.editor_action_bar.deleteRequested.connect(self.delete_upper_group)

        bulk_content = QWidget(self.bulk_panel)
        bulk_layout = QVBoxLayout(bulk_content)
        bulk_layout.setContentsMargins(10, 8, 10, 8)
        bulk_layout.setSpacing(8)
        bulk_layout.addWidget(QLabel(STOCK_MANAGER_BULK_TITLE, objectName="Section"))
        self.bulk_summary = QLabel("Seçili üst grup: 0", objectName="SubTitle")
        self.bulk_summary.setWordWrap(True)
        bulk_hint = QLabel("Seçilen üst gruplar üzerinde toplu silme işlemi yapabilirsin.", objectName="SubTitle")
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
        self.le_filter_search.setPlaceholderText("Ara: üst grup / kaynak")
        self.btn_reset_filters = _btn(STOCK_MANAGER_RESET_FILTERS_TEXT, "SoftDanger", 40)
        row_top.addWidget(self.le_filter_search, 1)
        row_top.addWidget(self.btn_reset_filters, 0)
        row_filters = QHBoxLayout()
        row_filters.setSpacing(8)
        self.cb_filter_source = SwitchSelectWidget(title="Kaynak", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_source.addItem("Kullanıcı", "user")
        self.cb_filter_source.addItem("Varsayılan", "default")
        row_filters.addWidget(self.cb_filter_source, 1)
        row_filters.addStretch(1)
        flt.addLayout(row_top)
        flt.addLayout(row_filters)

        self.records_list = ManagerCardsListWidget()
        self.records_list.set_pagination_enabled(True)
        self.records_list.record_selected.connect(self.on_select)
        self.records_list.bulk_selection_changed.connect(self._on_record_bulk_selection_changed)
        self.le_filter_search.textChanged.connect(self._apply_list_filters)
        self.cb_filter_source.currentIndexChanged.connect(self._apply_list_filters)
        self.btn_reset_filters.clicked.connect(self._reset_list_filters)
        self._workspace.set_editor_widget(self._editor_host)
        self._workspace.set_bulk_widget(bulk_content)
        self._workspace.set_filters_widget(filters_host)
        self._workspace.set_list_widget(self.records_list)
        splitter.setSizes([0, 1320])

        self._workspace_adapter = StockManagerWorkspaceBehaviorAdapter(
            self,
            list_widget_attr="records_list",
            edit_message="Düzenlemek için sağdaki listeden bir üst grup seç.",
            bulk_message="Toplu işlem için sağdaki listeden en az bir üst grubu SEÇ ile işaretle.",
        )
        self._workspace_behavior = self._workspace.create_behavior_controller(adapter=self._workspace_adapter)

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

    def _refresh_left_panel_header(self):
        mode = str(self._left_mode or "edit").lower()
        if mode == "new":
            self.left_panel_title.setText(STOCK_MANAGER_LEFT_NEW_TITLE)
            self.left_panel_hint.setText("Yeni üst grup adını girip kaydet.")
            return
        if mode == "bulk":
            self.left_panel_title.setText(STOCK_MANAGER_LEFT_BULK_TITLE)
            self.left_panel_hint.setText("Seçili üst gruplar için toplu işlemleri buradan yönet.")
            return
        self.left_panel_title.setText(STOCK_MANAGER_LEFT_EDIT_TITLE)
        rec = self._primary_selected_record()
        if rec is None:
            self.left_panel_hint.setText("Düzenlemek için sağdaki listeden bir üst grup seç.")
            return
        self.left_panel_hint.setText(f"Seçili üst grup: {str(rec.get('name') or '-').strip()}")

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

    def _sync_workspace_summary(self):
        self._workspace.set_records_summary_text(f"{self.records_list.shown_count()} / {len(self._records)} kayıt")
        self._workspace.set_filters_footer_text(f"Toplam üst grup: {len(self._records)}")

    def _update_bulk_panel_state(self):
        count = self.records_list.bulk_selected_count()
        self.bulk_summary.setText(f"Seçili üst grup: {count}")
        self.btn_bulk_delete.setEnabled(count > 0)
        self._sync_workspace_summary()

    def _reset_list_filters(self):
        self.le_filter_search.clear()
        self.cb_filter_source.setCurrentText("Tümü")
        self._apply_list_filters()

    def _apply_list_filters(
        self,
        *_args,
        keep_selected_id: Optional[int] = None,
        keep_bulk_selected_ids: Optional[list[int]] = None,
    ):
        rows = list(self._records)
        source_filter = self.cb_filter_source.currentData()
        if source_filter in {"user", "default"}:
            rows = [r for r in rows if str(r.get("source") or "").strip().lower() == source_filter]

        query = str(self.le_filter_search.text() or "").strip().casefold()
        if query:
            rows = [
                r
                for r in rows
                if query in str(r.get("name") or "").casefold()
                or query in str(r.get("extra") or "").casefold()
            ]

        active_id = keep_selected_id if keep_selected_id is not None else self.records_list.selected_record_id()
        bulk_ids = keep_bulk_selected_ids if keep_bulk_selected_ids is not None else self.records_list.bulk_selected_ids()
        self.records_list.set_items(rows, keep_selected_id=active_id, keep_bulk_selected_ids=bulk_ids)
        self._workspace.set_records_summary_text(f"{self.records_list.shown_count()} / {len(rows)} kayıt")
        self._workspace.set_filters_footer_text(
            f"Toplam üst grup: {len(rows)} | Seçili: {self.records_list.bulk_selected_count()}"
        )

    def _clear_bulk_selection(self):
        self.records_list.clear_bulk_selection()
        self._update_bulk_panel_state()
        if self._left_mode == "bulk" and self._is_editor_panel_open():
            self._close_editor_panel()
        else:
            self._sync_sidebar_state_from_splitter()

    def _bulk_delete_selected(self):
        records = self.records_list.bulk_selected_records()
        if not records:
            self.error("Hata", "Toplu silme için en az bir üst grup seç.")
            return
        if not self.confirm("Silme Onay", f"{len(records)} üst grup silinecek. Emin misin?"):
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
            res = action_delete_upper_group(pk=pk)
            if res.success:
                success += 1
            else:
                failed += 1
                failures.append(f"{pk}: {res.message}")
        self.refresh()
        if failed <= 0:
            self.info("OK", f"{success} üst grup silindi.")
            self._close_editor_panel()
            return
        self.error(
            "Kısmi Bağarı",
            f"{success} üst grup silindi, {failed} üst grup silinemedi."
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

    def _on_record_bulk_selection_changed(self, _count: int):
        self._update_bulk_panel_state()
        if self._left_mode == "bulk" and self._is_editor_panel_open() and self.records_list.bulk_selected_count() <= 0:
            self._close_editor_panel()
            return
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()

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

    def clear_form(self, *, clear_table_selection: bool = True):
        self.le_pk.clear()
        self.le_name.clear()
        if clear_table_selection:
            self.records_list.clear_active_selection()
            self.records_list.clear_bulk_selection()
        self._workspace.set_editor_action_delete_available(False)
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()

    def _set_list_loading(self, busy: bool, message: str = "Üst gruplar yükleniyor...") -> None:
        self._workspace.set_list_loading(bool(busy), message=message)

    def refresh(self):
        self._set_list_loading(True)
        try:
            keep_selected_id = self.records_list.selected_record_id()
            keep_bulk_ids = self.records_list.bulk_selected_ids()
            res = action_list_upper_group_records()
            self._records = []
            if not res.success:
                self.records_list.set_items([], keep_selected_id=None, keep_bulk_selected_ids=keep_bulk_ids)
                self.clear_form(clear_table_selection=False)
                self._update_bulk_panel_state()
                self.error("Hata", res.message)
                return

            sub_res = action_list_sub_groups(category=None, only_active=True)
            sub_counts: dict[str, int] = {}
            if sub_res.success:
                for rec in (sub_res.data.get("records", []) or []):
                    category = str(getattr(rec, "category", "") or "").strip()
                    if category:
                        sub_counts[category] = int(sub_counts.get(category, 0)) + 1

            for c in (res.data.get("records", []) or []):
                name = str(getattr(c, "name", "") or "").strip()
                pk = getattr(c, "pk", None)
                source = str(getattr(c, "source", "default") or "default").strip().lower() or "default"
                sub_count = int(sub_counts.get(name, 0))
                rec = {
                    "pk": pk,
                    "name": name,
                    "source": source,
                    "sub_count": sub_count,
                    "can_delete": int(pk or 0) > 0,
                }
                rec["title"] = name or "-"
                rec["subtitle"] = f"Alt Grup: {sub_count} adet"
                rec["extra"] = f"Kaynak: {'Kullanıcı' if source == 'user' else 'Varsayılan'}"
                rec["badge"] = "Üst Grup"
                self._records.append(rec)

            self._apply_list_filters(keep_selected_id=keep_selected_id, keep_bulk_selected_ids=keep_bulk_ids)
            self._update_bulk_panel_state()
            self._refresh_left_panel_header()
            self._sync_focus_guidance_state()
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
            return
        if rec is None:
            rec = self._primary_selected_record()
        if rec is None:
            if self._left_mode == "edit":
                self.clear_form(clear_table_selection=False)
            self._refresh_left_panel_header()
            self._sync_focus_guidance_state()
            return
        self.le_pk.setText(str(rec.get("pk") or ""))
        self.le_name.setText(str(rec.get("name") or ""))
        self._workspace.set_editor_action_delete_available(bool(rec.get("can_delete")))
        self._set_left_mode("edit")

    def save_or_update(self):
        name = (self.le_name.text() or "").strip()
        if not name:
            self.error("Hata", "Üst grup adı boş olamaz.")
            return
        pk_txt = (self.le_pk.text() or "").strip()
        if pk_txt:
            res = action_update_upper_group(pk=int(pk_txt), update_data={"name": name})
        else:
            res = action_create_upper_group(name=name)
        if res.success:
            self.info("OK", res.message or "İşlem bağarılı.")
            self.refresh()
            self.clear_form()
        else:
            self.error("Hata", f"{res.message}\n{res.data}")

    def delete_upper_group(self):
        pk_txt = (self.le_pk.text() or "").strip()
        if not pk_txt:
            self.error("Hata", "Silmek için listeden bir üst grup seç.")
            return
        if not self.confirm("Silme Onay", "Bu üst grup silinecek. Emin misin?"):
            return
        res = action_delete_upper_group(pk=int(pk_txt))
        if res.success:
            self.info("OK", res.message or "Silindi.")
            self.refresh()
            self.clear_form()
        else:
            self.error("Hata", f"{res.message}\n{res.data}")








