from __future__ import annotations
from .views import *
from .company_manager_dialog import ManagerCardsListWidget, StockManagerWorkspaceBehaviorAdapter

class WarehouseManagerDialog(FullscreenDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Depolar")
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

        self._left_stick_size = 520
        self._workspace = RecordWorkspaceScaffold(
            self,
            left_title=STOCK_MANAGER_LEFT_EDIT_TITLE,
            left_subtitle="Düzenlemek için sağdaki listeden bir depo seç.",
            filters_title=STOCK_MANAGER_FILTERS_TITLE,
            records_title="Depo Listesi",
            editor_canvas_color="#FFFFFF",
            editor_surface_color="#FFFFFF",
            style_sheet=None,
            shell_kwargs={**STOCK_MANAGER_WORKSPACE_SHELL_KWARGS, "left_stick_size": self._left_stick_size, "left_collapse_trigger": max(1, int(self._left_stick_size * 0.5))},
            sidebar_buttons=(
                {
                    "panel_id": "new",
                    "text": "",
                    "tooltip": "Yeni depo paneli",
                    "icon_path": str(ASSETS_DIR / "yeni-kayit.png"),
                    "shape": "circular",
                    "icon_scale": 1.28,
                },
                {
                    "panel_id": "edit",
                    "text": "",
                    "tooltip": "Depo düzenleme paneli",
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
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        self._manager_splitter = splitter
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
        self.le_pk = QLineEdit(); self.le_pk.setEnabled(False)
        self.le_name = QLineEdit(); self.le_name.setPlaceholderText("Örn: Ana Depo")
        self.le_code = QLineEdit(); self.le_code.setPlaceholderText("Kod (ops.)")
        self.le_manager = QLineEdit(); self.le_manager.setPlaceholderText("Sorumlu kişi (ops.)")
        self.le_phone = PhoneNumberInput(
            dial_codes=list(PHONE_DIAL_CODE_OPTIONS or []),
            default_code="+90",
            number_placeholder="5000000000",
        )
        self.le_email = QLineEdit(); self.le_email.setPlaceholderText("E-posta (ops.)")
        self.le_address = QLineEdit(); self.le_address.setPlaceholderText("Adres (ops.)")
        self.cb_city = SwitchSelectWidget(multi=False, include_all=False, empty_text="Seçiniz")
        self.cb_country = SwitchSelectWidget(multi=False, include_all=False, empty_text="Seçiniz")
        self.le_capacity = NumericPulseLineEdit(decimals=2); self.le_capacity.setPlaceholderText("Kapasite m3 (ops.)")
        self.le_note = QLineEdit(); self.le_note.setPlaceholderText("Not (ops.)")
        form.addRow("Depo Adı", self.le_name)
        form.addRow("Kod", self.le_code)
        form.addRow("Sorumlu", self.le_manager)
        form.addRow("Telefon", self.le_phone)
        form.addRow("E-posta", self.le_email)
        form.addRow("Adres", self.le_address)
        form.addRow("Ülke", self.cb_country)
        form.addRow("Şehir", self.cb_city)
        form.addRow("Kapasite (m3)", self.le_capacity)
        form.addRow("Not", self.le_note)

        self._workspace.use_default_editor_action_bar()
        self._workspace.set_editor_action_labels(
            clear_text=STOCK_MANAGER_CLEAR_TEXT,
            save_new_text="Depo Kaydet",
            save_edit_text=STOCK_MANAGER_SAVE_EDIT_TEXT,
            delete_text=STOCK_MANAGER_DELETE_TEXT,
        )
        self.btn_clear = self._workspace.editor_action_bar.clear_button
        self.btn_delete = self._workspace.editor_action_bar.delete_button
        self.btn_save = self._workspace.editor_action_bar.save_button

        self._workspace.editor_action_bar.clearRequested.connect(self.clear_form)
        self._workspace.editor_action_bar.deleteRequested.connect(self.delete_warehouse)
        self._workspace.editor_action_bar.saveRequested.connect(self.save_or_update)
        self.cb_country.currentIndexChanged.connect(self._on_country_changed)
        self._city_options_by_country = self._build_city_options_by_country()
        self._set_filter_options(self.cb_country, list(self._city_options_by_country.keys()))
        self.cb_country.setCurrentIndex(-1)
        self._reload_city_options(country=None, selected_city=None)

        bulk_content = QWidget(self.bulk_panel)
        bulk_layout = QVBoxLayout(bulk_content)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.setSpacing(8)
        bulk_layout.setContentsMargins(10, 8, 10, 8)
        bulk_layout.addWidget(QLabel(STOCK_MANAGER_BULK_TITLE, objectName="Section"))
        self.bulk_summary = QLabel("Seçili depo: 0", objectName="SubTitle")
        self.bulk_summary.setWordWrap(True)
        bulk_hint = QLabel("SEÇ ile bir veya daha fazla depo seçip toplu işlem panelini kullanabilirsin.", objectName="SubTitle")
        bulk_hint.setWordWrap(True)
        self.btn_bulk_clear = _btn(STOCK_MANAGER_BULK_CLEAR_TEXT, "Ghost", 42)
        self.btn_bulk_clear.clicked.connect(self._clear_bulk_selection)
        bulk_layout.addWidget(self.bulk_summary)
        bulk_layout.addWidget(bulk_hint)
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
        self.le_filter_search.setPlaceholderText("Genel Ara (depo, kod, sorumlu, Şehir, ülke, telefon, e-posta...)")
        self.btn_reset_filters = _btn(STOCK_MANAGER_RESET_FILTERS_TEXT, "SoftDanger", 40)
        row_top.addWidget(self.le_filter_search, 1)
        row_top.addWidget(self.btn_reset_filters, 0)
        row_filters = QHBoxLayout()
        row_filters.setSpacing(8)
        self.cb_filter_country = SwitchSelectWidget(title="Ülke", all_text="Tümü", multi=False, include_all=True)
        self.cb_filter_city = SwitchSelectWidget(title="Şehir", all_text="Tümü", multi=False, include_all=True)
        row_filters.addWidget(self.cb_filter_country, 1)
        row_filters.addWidget(self.cb_filter_city, 1)
        flt.addLayout(row_top)
        flt.addLayout(row_filters)
        self.records_list = ManagerCardsListWidget()
        self.records_list.record_selected.connect(self.on_select)
        self.records_list.bulk_selection_changed.connect(self._on_record_bulk_selection_changed)
        self.le_filter_search.textChanged.connect(self._apply_list_filters)
        self.cb_filter_city.currentIndexChanged.connect(self._apply_list_filters)
        self.cb_filter_country.currentIndexChanged.connect(self._apply_list_filters)
        self.btn_reset_filters.clicked.connect(self._reset_list_filters)
        self._workspace.set_editor_widget(form_host)
        self._workspace.set_bulk_widget(bulk_content)
        self._workspace.set_filters_widget(filters_host)
        self._workspace.set_list_widget(self.records_list)
        self._workspace.footer_bar.setObjectName("BottomBar")
        self._workspace.footer_bar.page_size_label.setText("Sayfa başına")
        splitter.setSizes([0, 1340])

        self._workspace_adapter = StockManagerWorkspaceBehaviorAdapter(
            self,
            list_widget_attr="records_list",
            edit_message="Düzenlemek için sağdaki listeden bir depo seç.",
            bulk_message="Toplu işlem için sağdaki listeden en az bir depoyu SEÇ ile işaretle.",
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
            self.left_panel_hint.setText("Yeni depo bilgilerini doldurup kaydet.")
            return
        if mode == "bulk":
            self.left_panel_title.setText(STOCK_MANAGER_LEFT_BULK_TITLE)
            self.left_panel_hint.setText("Seçili depolar için toplu işlemler burada görünür.")
            return
        self.left_panel_title.setText(STOCK_MANAGER_LEFT_EDIT_TITLE)
        rec = self._primary_selected_record()
        if rec is None:
            self.left_panel_hint.setText("Düzenlemek için sağdaki listeden bir depo seç.")
            return
        self.left_panel_hint.setText(f"Seçili depo: {str(rec.get('name') or '-').strip()}")

    def _set_left_mode(self, mode: str):
        mode_key = str(mode or "").lower()
        if mode_key not in {"new", "edit", "bulk"}:
            mode_key = "edit"
        self._left_mode = mode_key
        self._workspace.set_editor_action_mode(mode_key)
        show_editor = self._left_mode in {"new", "edit"}
        self._editor_scroll.setVisible(show_editor)
        self.bulk_panel.setVisible(not show_editor)
        self._update_bulk_panel_state()
        self._refresh_left_panel_header()
        self._sync_sidebar_state_from_splitter()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

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

    def _refresh_filter_options(self):
        cities = sorted({str(r.get("city") or "").strip() for r in self._records if str(r.get("city") or "").strip()})
        countries = sorted({str(r.get("country") or "").strip() for r in self._records if str(r.get("country") or "").strip()})
        self._set_filter_options(self.cb_filter_city, cities)
        self._set_filter_options(self.cb_filter_country, countries)

    @staticmethod
    def _normalize_text_key(value: Any) -> str:
        return str(value or "").strip().casefold()

    def _build_city_options_by_country(self) -> dict[str, list[str]]:
        countries = [str(c or "").strip() for c in (COUNTRY_OPTIONS or []) if str(c or "").strip()]
        mapped: dict[str, list[str]] = {}

        for country in countries:
            mapped.setdefault(country, [])

        for country_name, cities in (CITY_OPTIONS_BY_COUNTRY or {}).items():
            c_name = str(country_name or "").strip()
            if not c_name:
                continue
            bucket = mapped.setdefault(c_name, [])
            seen = {self._normalize_text_key(x) for x in bucket}
            for city in cities or []:
                city_name = str(city or "").strip()
                if not city_name:
                    continue
                key = self._normalize_text_key(city_name)
                if key in seen:
                    continue
                seen.add(key)
                bucket.append(city_name)

        for country_name in list(mapped.keys()):
            mapped[country_name] = sorted(mapped[country_name], key=lambda x: x.casefold())

        return mapped

    def _find_country_label(self, value: Any) -> Optional[str]:
        key = self._normalize_text_key(value)
        if not key:
            return None
        for country in self._city_options_by_country.keys():
            if self._normalize_text_key(country) == key:
                return country
        return None

    def _reload_city_options(self, country: Any, selected_city: Any) -> None:
        country_label = self._find_country_label(country)
        if country_label:
            city_values = list(self._city_options_by_country.get(country_label, []))
        else:
            city_values = []

        selected_city_text = str(selected_city or "").strip()
        self._set_filter_options(self.cb_city, city_values)

        if selected_city_text:
            idx = self.cb_city.findText(selected_city_text)
            if idx < 0:
                self.cb_city.addItem(selected_city_text, selected_city_text)
                idx = self.cb_city.findText(selected_city_text)
            self.cb_city.setCurrentIndex(idx)
        else:
            self.cb_city.setCurrentIndex(-1)

    def _on_country_changed(self, _index: int) -> None:
        country = self.cb_country.currentData()
        self._reload_city_options(country=country, selected_city=None)
        _sync_phone_country_code(self.le_phone, country)

    def _reset_list_filters(self):
        self.le_filter_search.clear()
        self.cb_filter_city.setCurrentText("Tümü")
        self.cb_filter_country.setCurrentText("Tümü")
        self._apply_list_filters()

    def _apply_list_filters(
        self,
        *_args,
        keep_selected_id: Optional[int] = None,
        keep_bulk_selected_ids: Optional[list[int]] = None,
    ):
        rows = list(self._records)

        city_filter = self.cb_filter_city.currentData()
        if city_filter not in (None, "all"):
            rows = [r for r in rows if str(r.get("city") or "").strip().casefold() == str(city_filter).strip().casefold()]

        country_filter = self.cb_filter_country.currentData()
        if country_filter not in (None, "all"):
            rows = [r for r in rows if str(r.get("country") or "").strip().casefold() == str(country_filter).strip().casefold()]

        q = (self.le_filter_search.text() or "").strip().casefold()
        if q:
            def _hit(value: Any) -> bool:
                return q in str(value or "").casefold()

            rows = [
                r for r in rows
                if _hit(r.get("name"))
                or _hit(r.get("code"))
                or _hit(r.get("manager_name"))
                or _hit(r.get("phone"))
                or _hit(r.get("email"))
                or _hit(r.get("address"))
                or _hit(r.get("city"))
                or _hit(r.get("country"))
                or _hit(r.get("capacity_m3"))
                or _hit(r.get("note"))
            ]

        active_id = keep_selected_id if keep_selected_id is not None else self.records_list.selected_record_id()
        bulk_ids = keep_bulk_selected_ids if keep_bulk_selected_ids is not None else self.records_list.bulk_selected_ids()
        self.records_list.set_items(rows, keep_selected_id=active_id, keep_bulk_selected_ids=bulk_ids)
        self._workspace.footer_bar.refresh()
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
        self.clear_form()
        self._set_left_mode("new")

    def _clear_manager_workspace_state(self):
        self.clear_form()

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
        self.bulk_summary.setText(f"Seçili depo: {count}")
        self._sync_workspace_summary()

    def _clear_bulk_selection(self):
        self.records_list.clear_bulk_selection()
        self._update_bulk_panel_state()
        if self._left_mode == "bulk" and self._is_editor_panel_open():
            self._close_editor_panel()
        else:
            self._sync_sidebar_state_from_splitter()

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
        self.le_code.clear()
        self.le_manager.clear()
        self.le_phone.clear()
        self.le_email.clear()
        self.le_address.clear()
        self.cb_country.setCurrentIndex(-1)
        self._reload_city_options(country=None, selected_city=None)
        self.le_capacity.setText("")
        self.le_note.clear()
        if clear_table_selection:
            self.records_list.clear_active_selection()
            self.records_list.clear_bulk_selection()
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def _selected_record(self) -> Optional[dict[str, Any]]:
        pk_txt = (self.le_pk.text() or "").strip()
        if not pk_txt:
            return None
        try:
            pk = int(pk_txt)
        except Exception:
            return None
        return next((r for r in self._records if int(r.get("pk") or 0) == pk), None)

    def _set_list_loading(self, busy: bool, message: str = "Depolar yükleniyor...") -> None:
        self._workspace.set_list_loading(bool(busy), message=message)

    def refresh(self):
        self._set_list_loading(True)
        try:
            keep_selected_id = self.records_list.selected_record_id()
            keep_bulk_ids = self.records_list.bulk_selected_ids()
            res = action_list_warehouses()
            self._records = []
            if not res.success:
                self.records_list.set_items([], keep_selected_id=None, keep_bulk_selected_ids=keep_bulk_ids)
                self._refresh_filter_options()
                self.clear_form(clear_table_selection=False)
                self._update_bulk_panel_state()
                self._refresh_left_panel_header()
                self._sync_focus_guidance_state()
                self._update_edit_lock_state()
                self.error("Hata", res.message)
                return

            records = res.data.get("records", []) or []
            for wh in records:
                row = {
                    "pk": getattr(wh, "pk", None),
                    "name": getattr(wh, "name", None),
                    "code": getattr(wh, "code", None),
                    "manager_name": getattr(wh, "manager_name", None),
                    "phone": getattr(wh, "phone", None),
                    "email": getattr(wh, "email", None),
                    "address": getattr(wh, "address", None),
                    "city": getattr(wh, "city", None),
                    "country": getattr(wh, "country", None),
                    "capacity_m3": getattr(wh, "capacity_m3", None),
                    "note": getattr(wh, "note", None),
                }
                row["title"] = str(row.get("name") or "-")
                row["subtitle"] = f"Kod: {str(row.get('code') or '-')} • Şehir: {str(row.get('city') or '-')}"
                row["extra"] = f"Telefon: {str(row.get('phone') or '-')}"
                self._records.append(row)

            self._refresh_filter_options()
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
        if not rec:
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
        self.le_code.setText(str(rec.get("code") or ""))
        self.le_manager.setText(str(rec.get("manager_name") or ""))
        self.le_phone.setText(str(rec.get("phone") or ""))
        self.le_email.setText(str(rec.get("email") or ""))
        self.le_address.setText(str(rec.get("address") or ""))
        country_text = str(rec.get("country") or "").strip()
        city_text = str(rec.get("city") or "").strip()
        if country_text:
            idx = self.cb_country.findText(country_text)
            if idx < 0:
                self.cb_country.addItem(country_text, country_text)
                idx = self.cb_country.findText(country_text)
            self.cb_country.setCurrentIndex(idx)
        else:
            self.cb_country.setCurrentIndex(-1)
        self._reload_city_options(country=country_text, selected_city=city_text)
        if rec.get("capacity_m3") is not None:
            self.le_capacity.setValue(float(rec.get("capacity_m3")))
        else:
            self.le_capacity.setText("")
        self.le_note.setText(str(rec.get("note") or ""))
        self._refresh_left_panel_header()
        self._sync_focus_guidance_state()
        self._update_edit_lock_state()

    def save_or_update(self):
        name = (self.le_name.text() or "").strip()
        if not name:
            self.error("Hata", "Depo adı boş olamaz.")
            return

        pk_txt = (self.le_pk.text() or "").strip()
        payload = {
            "name": name,
            "code": (self.le_code.text() or "").strip() or None,
            "manager_name": (self.le_manager.text() or "").strip() or None,
            "phone": self.le_phone.value(),
            "email": (self.le_email.text() or "").strip() or None,
            "address": (self.le_address.text() or "").strip() or None,
            "city": (str(self.cb_city.currentData() or "").strip() or None),
            "country": (str(self.cb_country.currentData() or "").strip() or None),
            "capacity_m3": float(self.le_capacity.value()) if self.le_capacity.has_value() else None,
            "note": (self.le_note.text() or "").strip() or None,
        }
        res = action_update_warehouse(pk=int(pk_txt), update_data=payload) if pk_txt else action_create_warehouse(**payload)

        if res.success:
            self.info("OK", res.message or "İşlem bağarılı.")
            self.refresh()
            self._open_new_form()
        else:
            self.error("Hata", f"{res.message}\n{res.data}")

    def delete_warehouse(self):
        pk_txt = (self.le_pk.text() or "").strip()
        if not pk_txt:
            self.error("Hata", "Silmek için listeden bir depo seç.")
            return

        if not self.confirm("Silme Onay", "Bu depo silinecek. Emin misin?"):
            return

        pk = int(pk_txt)
        res = action_delete_warehouse(pk=pk)
        if res.success:
            self.info("OK", res.message or "Depo silindi.")
            self.refresh()
            self.records_list.clear_active_selection()
            self.records_list.clear_bulk_selection()
            self.clear_form(clear_table_selection=False)
            self._close_editor_panel()
            return
        self.error("Hata", res.message or "Depo silinemedi.")


# =========================================================
# ? Sub Group Manager
# =========================================================







