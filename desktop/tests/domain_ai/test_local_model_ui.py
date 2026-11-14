from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from AI.views.ai_manager_dialog import AIManagerDialog


class TestLocalModelHubUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make_dialog(self) -> AIManagerDialog:
        with ExitStack() as patches:
            for method in ("_load_settings", "_load_provider_accounts", "_refresh_library", "_start_search"):
                patches.enter_context(patch.object(AIManagerDialog, method))
            dialog = AIManagerDialog()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog

    def test_download_location_and_separate_installed_library_are_accessible(self) -> None:
        dialog = self.make_dialog()
        dialog._set_entry_kind("local")
        dialog.show()
        self.app.processEvents()

        self.assertTrue(dialog.btn_local_choose_root.isVisibleTo(dialog))
        self.assertFalse(dialog.installed_local_list.isVisibleTo(dialog))
        dialog.local_library_tabs.setCurrentIndex(1)
        self.app.processEvents()
        self.assertTrue(dialog.installed_local_list.isVisibleTo(dialog))
        self.assertFalse(dialog.results_list.isVisibleTo(dialog))
        self.assertTrue(dialog.download_progress.isVisibleTo(dialog))
        self.assertIs(dialog.local_search_panel.parent(), dialog._workspace.records_card.body_host)
        self.assertFalse(dialog.records_list.isVisibleTo(dialog))
        dialog._set_entry_kind("cloud")
        self.assertTrue(dialog.records_list.isVisibleTo(dialog))
        self.assertFalse(dialog.local_search_panel.isVisibleTo(dialog))

    def test_bulk_mode_restores_connected_sources_after_local_browsing(self) -> None:
        dialog = self.make_dialog()
        dialog._set_entry_kind("local")
        dialog._set_provider_mode("bulk")
        self.assertTrue(dialog.local_search_panel.isHidden())
        self.assertFalse(dialog.records_list.isHidden())

    def test_insufficient_download_disk_disables_download_with_reason(self) -> None:
        dialog = self.make_dialog()
        with patch.object(dialog, "_download_disk_free", return_value=1024 ** 3):
            dialog.file_combo.addItem("large.gguf", {"filename": "large.gguf", "size_bytes": 2 * 1024 ** 3})
            dialog._update_download_file_plan()

        self.assertFalse(dialog.btn_download.isEnabled())
        self.assertIn("yeterli disk alanı yok", dialog.local_file_plan.text())

    def test_auxiliary_gguf_is_never_presented_as_ready_for_chat(self) -> None:
        dialog = self.make_dialog()
        dialog._fill_installed_local_list([{
            "id": 42, "repo_id": "example/model-mtp", "filename": "mtp.gguf", "exists_on_disk": True,
            "resource_plan": {"safe_to_run": False, "suitability": "blocked", "capacity_label": "Sohbet modeli değil"},
        }])
        self.assertIn("uygun değil", dialog.installed_local_list.item(0).text())
        self.assertIn("Sohbet modeli değil", dialog.installed_local_detail.text())

    def test_clearing_model_details_preserves_download_progress(self) -> None:
        dialog = self.make_dialog()
        dialog.download_progress.setValue(43)
        dialog._clear_detail()
        self.assertEqual(dialog.download_progress.value(), 43)

    def test_folder_hint_measures_the_selected_drive(self) -> None:
        dialog = self.make_dialog()
        with tempfile.TemporaryDirectory() as directory:
            dialog._settings = {"download_root": str(Path(directory) / "models")}
            dialog._sync_local_download_location()
            self.assertIn("GiB boş alan", dialog.local_download_root_label.text())
            self.assertIn("models", dialog.local_download_root_label.text())


class TestLocalModelSettingsUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make_dialog(self, on_apply):
        from AI.views.chat_tab import _AdvancedModelSettingsDialog

        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        dialog = _AdvancedModelSettingsDialog(parent, record={
            "repo_id": "example/4b", "runtime_config": {"num_gpu": 0},
            "resource_plan": {"safe_to_run": True, "num_ctx": 8192, "max_tokens": 2048},
        }, is_local=True, on_apply=on_apply)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog

    def test_effective_limits_and_explicit_cpu_mode_are_preserved(self) -> None:
        dialog = self.make_dialog(lambda _values: None)
        self.assertEqual(dialog._fields["num_ctx"].text(), "8192")
        self.assertEqual(dialog._fields["max_tokens"].text(), "2048")
        self.assertEqual(dialog._fields["num_gpu"].text(), "0")
        self.assertTrue(dialog._advanced_fields_panel.isHidden())
        self.assertGreaterEqual(dialog._performance_preset.findData("quality"), 0)

    def test_invalid_numeric_setting_stays_open_without_applying(self) -> None:
        applied = []
        dialog = self.make_dialog(applied.append)
        dialog._fields["num_thread"].setText("many")
        dialog._apply()
        self.assertEqual(applied, [])
        self.assertFalse(dialog.validation_label.isHidden())

    def test_decimal_comma_and_quality_profile_are_applied(self) -> None:
        applied = []
        dialog = self.make_dialog(applied.append)
        dialog._fields["temperature"].setText("0,35")
        dialog._performance_preset.setCurrentIndex(dialog._performance_preset.findData("quality"))
        dialog._apply()
        self.assertEqual(applied[0]["temperature"], 0.35)
        self.assertEqual(applied[0]["num_gpu"], 0)
        self.assertEqual(applied[0]["performance_preset"], "quality")

    def test_economy_profile_updates_visible_context_and_answer_budget(self) -> None:
        dialog = self.make_dialog(lambda _values: None)
        dialog._performance_preset.setCurrentIndex(dialog._performance_preset.findData("eco"))
        self.assertEqual(dialog._fields["num_ctx"].text(), "4096")
        self.assertEqual(dialog._fields["max_tokens"].text(), "1024")


if __name__ == "__main__":
    unittest.main()
