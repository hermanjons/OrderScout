from __future__ import annotations

import inspect
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import Account.views.company_manager_dialog as company_manager_dialog_module
import Account.views.views as account_views_module
from PyQt6.QtWidgets import QApplication, QWidget

from Account.views.views import CompanyManagerDialog
from Account.views.company_list_widget import CompanyListWidget
from Feedback.processors.pipeline import Result
from Core.views import FileBadgePicker, RecordWorkspaceEditorActionBar, RecordWorkspaceListDelegate, ResettableSplitter, SwitchSelectWidget


class TestAccountViews(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _dialog(self) -> CompanyManagerDialog:
        dialog = CompanyManagerDialog()
        self.addCleanup(dialog.close)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(self._app.processEvents)
        return dialog

    def test_company_manager_dialog_uses_core_widgets(self) -> None:
        dialog = self._dialog()
        self.assertIsInstance(dialog.platform_input, SwitchSelectWidget)
        self.assertIsInstance(dialog.logo_selector, FileBadgePicker)

    def test_company_manager_dialog_uses_core_splitter(self) -> None:
        dialog = self._dialog()
        splitter = dialog.findChild(ResettableSplitter)
        self.assertIsNotNone(splitter)

    def test_company_manager_dialog_uses_scaffold_action_surface(self) -> None:
        dialog = self._dialog()
        self.assertEqual(dialog.btn_new.objectName(), "Ghost")
        self.assertEqual(dialog.btn_save.objectName(), "Primary")
        self.assertEqual(dialog.btn_delete.objectName(), "Danger")
        self.assertEqual(dialog._workspace.editor_actions_card.objectName(), "SoftCard")
        self.assertIs(dialog.btn_save.parentWidget(), dialog._workspace.editor_action_bar)
        self.assertIsInstance(dialog._workspace.editor_action_bar, RecordWorkspaceEditorActionBar)
        self.assertEqual(dialog._workspace.editor_action_bar.mode(), "edit")

    def test_company_manager_dialog_scaffold_action_bar_switches_labels_by_mode(self) -> None:
        dialog = self._dialog()

        dialog._set_left_mode("new")
        self.assertEqual(dialog.btn_save.text(), "API Kaydet")
        self.assertTrue(dialog.btn_delete.isHidden())

        dialog._set_left_mode("edit")
        self.assertEqual(dialog.btn_save.text(), "Güncelle")
        self.assertFalse(dialog.btn_delete.isHidden())

    def test_company_manager_dialog_uses_core_card_delegate_contract(self) -> None:
        dialog = self._dialog()
        delegate = dialog.list_view.itemDelegate()
        self.assertIsInstance(delegate, RecordWorkspaceListDelegate)
        self.assertEqual(delegate.sizeHint(None, None).height(), 78)

    def test_company_manager_dialog_requests_white_editor_surface(self) -> None:
        dialog = self._dialog()
        self.assertIn("#FFFFFF", dialog._workspace.editor_host.styleSheet())
        self.assertIn("#FFFFFF", dialog._workspace.editor_scroll.styleSheet())
        self.assertIn("#FFFFFF", dialog._workspace.editor_surface.styleSheet())

    def test_company_manager_dialog_platform_summary_skips_tooltip_when_text_fits(self) -> None:
        dialog = self._dialog()
        dialog.resize(1280, 800)
        dialog.platform_input.setCurrentText("Amazon")
        dialog.platform_input.resize(420, dialog.platform_input.height() or 46)
        dialog.platform_input.show()
        self._app.processEvents()

        self.assertEqual(dialog.platform_input._summary.text(), "Amazon")
        self.assertEqual(dialog.platform_input._summary.toolTip(), "")

    def test_account_views_module_is_thin_orchestrator(self) -> None:
        source = inspect.getsource(account_views_module)
        self.assertNotIn("CompanyListWidget", source)
        self.assertNotIn("AnimatedGuidanceRing", source)
        self.assertNotIn("EditLockOverlay", source)

    def test_company_list_widget_lives_outside_views_orchestrator(self) -> None:
        widget = CompanyListWidget()
        self.addCleanup(widget.deleteLater)
        self.assertIsInstance(widget, CompanyListWidget)

    def test_company_manager_dialog_restores_active_edit_selection_after_reload(self) -> None:
        dialog = self._dialog()

        first = SimpleNamespace(
            pk=11,
            account_id="A11",
            comp_name="Alpha",
            platform="trendyol",
            api_key="k1",
            api_secret="s1",
            integration_code="i1",
            token="t1",
            extra_config={"x": 1},
            is_active=True,
            token_valid=True,
            logo_path="",
        )
        second = SimpleNamespace(
            pk=22,
            account_id="B22",
            comp_name="Beta",
            platform="amazon",
            api_key="k2",
            api_secret="s2",
            integration_code="i2",
            token="t2",
            extra_config={"x": 2},
            is_active=True,
            token_valid=True,
            logo_path="",
        )
        dialog.list_model.set_companies([first, second])
        dialog._activate_row_for_edit(1, allow_toggle=False)
        dialog.list_model.set_companies([first, second])

        restored = dialog._restore_account_selection(22)

        self.assertTrue(restored)
        self.assertIsNotNone(dialog.account)
        self.assertEqual(getattr(dialog.account, "pk", None), 22)
        self.assertEqual(dialog.list_model.selected_row(), 1)

    def test_company_manager_dialog_health_payload_preserves_integration_code(self) -> None:
        dialog = self._dialog()
        account = SimpleNamespace(
            pk=7,
            comp_name="Gamma",
            platform="trendyol",
            account_id="70007",
            api_key="key",
            api_secret="secret",
            integration_code="INT-70007",
            token="token",
            extra_config={"region": "tr"},
        )

        payload = dialog._health_payload_for_account(account)

        self.assertEqual(payload["integration_code"], "INT-70007")
        self.assertEqual(payload["extra_config"], {"region": "tr"})

    def test_company_list_widget_preserves_selection_on_rebuild(self) -> None:
        widget = CompanyListWidget()
        self.addCleanup(widget.close)
        self.addCleanup(widget.deleteLater)

        first = SimpleNamespace(pk=1, comp_name="Alpha", account_id="A1", logo_path="")
        second = SimpleNamespace(pk=2, comp_name="Beta", account_id="B2", logo_path="")
        result = Result.ok("ok", close_dialog=False, data={"records": [first, second]})

        widget._safe_build(result)
        first_item_widget = widget.itemWidget(widget.item(0))
        second_item_widget = widget.itemWidget(widget.item(1))
        first_item_widget.right_widget.setChecked(False)
        second_item_widget.right_widget.setChecked(True)

        widget._safe_build(result, selected_pks={2})

        rebuilt_first = widget.itemWidget(widget.item(0))
        rebuilt_second = widget.itemWidget(widget.item(1))
        self.assertFalse(rebuilt_first.right_widget.isChecked())
        self.assertTrue(rebuilt_second.right_widget.isChecked())

    def test_company_manager_dialog_workspace_handlers_drop_legacy_fallbacks(self) -> None:
        methods = (
            CompanyManagerDialog._refresh_company_list_layout,
            CompanyManagerDialog._sync_sidebar_state_from_splitter,
            CompanyManagerDialog._sync_workspace_summary,
            CompanyManagerDialog._sync_card_spin_state,
        )
        combined = "\n".join(inspect.getsource(method) for method in methods)
        self.assertNotIn('hasattr(self, "list_view")', combined)
        self.assertNotIn('getattr(self, "_workspace_controller"', combined)
        self.assertNotIn('hasattr(self, "list_model")', combined)
        self.assertNotIn('hasattr(self, "_workspace")', combined)
        self.assertNotIn('hasattr(self, "company_total_label")', combined)

    def test_company_manager_dialog_module_drops_legacy_company_list_classes_and_handlers(self) -> None:
        source = inspect.getsource(company_manager_dialog_module)
        self.assertNotIn("class AnimatedGuidanceRing(", source)
        self.assertNotIn("class EditLockOverlay(", source)
        self.assertNotIn("fallback_total_width", source)
        self.assertNotIn("class CompanyListModel(", source)
        self.assertNotIn("class CompanyListDelegate(", source)
        self.assertNotIn("def _on_row_clicked(", source)
        self.assertNotIn("def _on_select_button_clicked(", source)
        self.assertNotIn("def _on_panel_sidebar_toggled(", source)
        self.assertNotIn("def _on_list_blank_area_clicked(", source)
        self.assertNotIn("def _splitter_total_size(", source)
        self.assertNotIn("def _snap_splitter(", source)
        self.assertNotIn("def _restart_splitter_settle_timer(", source)
        self.assertNotIn("def _settle_company_splitter(", source)
        self.assertNotIn("class CompanyListWidget(", source)


if __name__ == "__main__":
    unittest.main()
