from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel

from AI.views.ai_manager_dialog import AIManagerDialog
from Feedback.processors.pipeline import Result


class TestAiManagerDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in list(self._app.topLevelWidgets()):
            try:
                widget.close()
            except Exception:
                pass
            try:
                widget.deleteLater()
            except Exception:
                pass
        self._app.processEvents()

    def test_local_record_edit_mode_keeps_model_hub_download_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "gpt-oss-20b-q4_k_m.gguf"
            model_path.write_bytes(b"fake")
            record = {
                "repo_id": "openai/gpt-oss-20b",
                "filename": model_path.name,
                "local_path": str(model_path),
                "file_format": "GGUF",
                "size_text": "13 GB",
                "exists_on_disk": True,
            }
            runtime_payload = {
                "record": dict(record),
                "config": {
                    "runtime_strategy": "llama_cpp",
                    "performance_preset": "eco",
                    "reasoning_effort": "low",
                    "num_ctx": 1024,
                    "max_tokens": 256,
                    "num_thread": 4,
                    "num_batch": 16,
                    "num_gpu": 8,
                    "keep_alive": "0s",
                    "use_mmap": True,
                    "use_mlock": False,
                    "allow_unsafe": False,
                },
                "capabilities": {
                    "supports_reasoning_effort": True,
                    "supports_mmap": True,
                    "supports_keep_alive": True,
                    "runtime_sources": ["llama_cpp"],
                },
                "resource_plan": {
                    "profile": "balanced_large_model",
                    "num_ctx": 1024,
                    "max_tokens": 256,
                    "num_thread": 4,
                    "num_gpu": 8,
                    "offload_strategy": "disk_mmap_gpu_cpu",
                    "use_mmap": True,
                    "memory_pressure": 0.75,
                    "performance_score": 92.2,
                },
            }

            with patch("AI.views.actions.action_load_ai_settings", return_value=Result.ok(close_dialog=False, data={"settings": {}})), patch(
                "AI.views.actions.action_list_provider_accounts",
                return_value=Result.ok(close_dialog=False, data={"records": []}),
            ), patch(
                "AI.views.actions.action_list_installed_models",
                return_value=Result.ok(close_dialog=False, data={"records": []}),
            ), patch(
                "AI.views.actions.action_search_hf_models",
                return_value=Result.ok(close_dialog=False, data={"records": []}),
            ), patch(
                "AI.views.actions.action_get_local_model_runtime_config",
                return_value=Result.ok(close_dialog=False, data=runtime_payload),
            ) as config_mock:
                dialog = AIManagerDialog()
                self.addCleanup(dialog.close)
                self.addCleanup(dialog.deleteLater)
                dialog._active_workspace_payload = {"kind": "local", "record": dict(record)}
                dialog._set_provider_mode("edit")
                self._app.processEvents()

            self.assertFalse(dialog.local_search_panel.isHidden())
            self.assertTrue(dialog.local_config_panel.isHidden())
            self.assertTrue(dialog._workspace.editor_action_bar.isHidden())
            self.assertFalse(dialog.btn_save_provider.isEnabled())
            self.assertEqual(dialog.btn_save_provider.text(), "İndirme panelini kullan")
            config_mock.assert_not_called()

    def test_provider_model_picker_is_not_exposed_in_model_hub(self) -> None:
        with patch("AI.views.actions.action_load_ai_settings", return_value=Result.ok(close_dialog=False, data={"settings": {}})), patch(
            "AI.views.actions.action_list_provider_accounts",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch(
            "AI.views.actions.action_list_installed_models",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch(
            "AI.views.actions.action_search_hf_models",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ):
            dialog = AIManagerDialog()
            self.addCleanup(dialog.close)
            self.addCleanup(dialog.deleteLater)

        self.assertTrue(dialog.provider_model_input.isHidden())
        self.assertTrue(dialog.provider_model_combo.isHidden())
        self.assertTrue(dialog.provider_free_only_checkbox.isHidden())
        self.assertTrue(dialog.btn_load_provider_models.isHidden())
        self.assertTrue(dialog.provider_reasoning_combo.isHidden())
        notes = [label.text() for label in dialog.provider_editor.findChildren(QLabel)]
        self.assertTrue(any("Model ve zekâ ayarı burada yapılmaz" in text for text in notes))

    def test_model_hub_opens_new_resource_mode_with_scaffold_panel_visible(self) -> None:
        with patch("AI.views.actions.action_load_ai_settings", return_value=Result.ok(close_dialog=False, data={"settings": {}})), patch(
            "AI.views.actions.action_list_provider_accounts",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch(
            "AI.views.actions.action_list_installed_models",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch(
            "AI.views.actions.action_search_hf_models",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ):
            dialog = AIManagerDialog()
            self.addCleanup(dialog.close)
            self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog._provider_mode, "new")
        self.assertGreater(dialog._workspace.shell.splitter.sizes()[0], 0)
        self.assertTrue(dialog._workspace.filters_card.isHidden())
        self.assertTrue(dialog._workspace.footer_bar.isHidden())
        self.assertEqual(dialog.btn_save_provider.text(), "Bağlantıyı doğrula ve kaydet")

    def test_cloud_connection_validation_is_inline_and_does_not_call_save_action(self) -> None:
        with patch("AI.views.actions.action_load_ai_settings", return_value=Result.ok(close_dialog=False, data={"settings": {}})), patch(
            "AI.views.actions.action_list_provider_accounts",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch(
            "AI.views.actions.action_list_installed_models",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch(
            "AI.views.actions.action_search_hf_models",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch("AI.views.actions.action_save_provider_account") as save_mock:
            dialog = AIManagerDialog()
            self.addCleanup(dialog.close)
            self.addCleanup(dialog.deleteLater)
            dialog._set_provider_mode("new")
            dialog._set_entry_kind("cloud")
            dialog.provider_label_input.clear()
            dialog.provider_key_input.clear()

            dialog._save_provider_account()

        save_mock.assert_not_called()
        self.assertFalse(dialog.provider_validation_label.isHidden())
        self.assertIn("Bağlantı adı", dialog.provider_validation_label.text())
        self.assertIn("API anahtarı", dialog.provider_validation_label.text())
        self.assertTrue(dialog.provider_label_input.property("validationError"))
        self.assertTrue(dialog.provider_key_input.property("validationError"))

    def test_model_hub_scope_note_moves_reasoning_to_chat(self) -> None:
        with patch("AI.views.actions.action_load_ai_settings", return_value=Result.ok(close_dialog=False, data={"settings": {}})), patch(
            "AI.views.actions.action_list_provider_accounts",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch(
            "AI.views.actions.action_list_installed_models",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch(
            "AI.views.actions.action_search_hf_models",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ):
            dialog = AIManagerDialog()
            self.addCleanup(dialog.close)
            self.addCleanup(dialog.deleteLater)

        self.assertTrue(dialog.provider_reasoning_combo.isHidden())
        self.assertTrue(dialog.provider_reasoning_status.isHidden())
        self.assertIn("reasoning/zekâ seviyesi", dialog.hub_scope_note.text())

    def test_connected_sources_group_local_artifacts_under_one_download_entry(self) -> None:
        with patch("AI.views.actions.action_load_ai_settings", return_value=Result.ok(close_dialog=False, data={"settings": {}})), patch(
            "AI.views.actions.action_list_provider_accounts",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch(
            "AI.views.actions.action_list_installed_models",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ), patch(
            "AI.views.actions.action_search_hf_models",
            return_value=Result.ok(close_dialog=False, data={"records": []}),
        ):
            dialog = AIManagerDialog()
            self.addCleanup(dialog.close)
            self.addCleanup(dialog.deleteLater)

        dialog._provider_records = [
            {
                "id": 7,
                "provider_code": "gemini",
                "provider_label": "Google AI Studio",
                "label": "Google AI Studio",
                "api_key_masked": "••••1234",
                "is_enabled": True,
            }
        ]
        dialog._library_records = [
            {"id": index, "repo_id": f"orderscout/model-{index}", "exists_on_disk": True}
            for index in range(1, 4)
        ]
        dialog._rebuild_workspace_records()

        self.assertEqual(len(dialog._workspace_card_records), 2)
        payloads = [dialog._workspace_record_payload(record) for record in dialog._workspace_card_records]
        self.assertEqual([payload.get("kind") for payload in payloads], ["cloud", "local_library"])
        self.assertEqual(dialog._workspace_card_records[0].action_text, "Bağlantıyı düzenle")
        self.assertEqual(dialog._workspace_card_records[1].action_text, "Yerel indir")
        self.assertEqual(len(payloads[1].get("records") or []), 3)

    def test_local_download_pause_requests_cooperative_stop(self) -> None:
        class PauseWorker:
            def __init__(self) -> None:
                self.requested = False

            def isRunning(self) -> bool:
                return True

            def request_pause(self) -> None:
                self.requested = True

        with patch("AI.views.actions.action_load_ai_settings", return_value=Result.ok(close_dialog=False, data={"settings": {}})), patch(
            "AI.views.actions.action_list_provider_accounts", return_value=Result.ok(close_dialog=False, data={"records": []})
        ), patch(
            "AI.views.actions.action_list_installed_models", return_value=Result.ok(close_dialog=False, data={"records": []})
        ), patch(
            "AI.views.actions.action_search_hf_models", return_value=Result.ok(close_dialog=False, data={"records": []})
        ):
            dialog = AIManagerDialog()
            self.addCleanup(dialog.close)
            self.addCleanup(dialog.deleteLater)
            worker = PauseWorker()
            dialog._download_worker = worker
            dialog.btn_pause_download.setEnabled(True)

            dialog._pause_download()

        self.assertTrue(worker.requested)
        self.assertFalse(dialog.btn_pause_download.isEnabled())
        self.assertIn("duraklatılıyor", dialog.download_stage.text())

    def test_local_library_delete_uses_confirmation_and_refreshes_records(self) -> None:
        with patch("AI.views.actions.action_load_ai_settings", return_value=Result.ok(close_dialog=False, data={"settings": {}})), patch(
            "AI.views.actions.action_list_provider_accounts", return_value=Result.ok(close_dialog=False, data={"records": []})
        ), patch(
            "AI.views.actions.action_list_installed_models", return_value=Result.ok(close_dialog=False, data={"records": []})
        ), patch(
            "AI.views.actions.action_search_hf_models", return_value=Result.ok(close_dialog=False, data={"records": []})
        ), patch.object(
            AIManagerDialog, "_refresh_library"
        ) as refresh_mock, patch(
            "AI.views.ai_manager_dialog.AppMessageCenter.confirm", return_value=True
        ) as confirm_mock, patch(
            "AI.views.actions.action_delete_installed_model",
            return_value=Result.ok("Yerel model dosyası ve kaydı silindi.", close_dialog=False),
        ) as delete_mock:
            dialog = AIManagerDialog()
            self.addCleanup(dialog.close)
            self.addCleanup(dialog.deleteLater)
            refresh_mock.reset_mock()
            dialog._fill_installed_local_list(
                [{"id": 42, "repo_id": "orderscout/local", "filename": "local.gguf", "size_text": "1 GB"}]
            )
            dialog.installed_local_list.setCurrentRow(0)

            dialog._delete_selected_local_model()

        confirm_mock.assert_called_once()
        delete_mock.assert_called_once_with(42)
        refresh_mock.assert_called_once()
        self.assertIn("silindi", dialog.download_stage.text())


if __name__ == "__main__":
    unittest.main()
