from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from Feedback.processors.pipeline import Result
import Update.views.runner_app as runner_app
from Update.views.runner_app import InstallerRunnerController
from Update.views.updater_runner_dialog import UpdaterRunnerDialog


class TestUpdateRunnerUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_runner_dialog_uses_compact_progress_layout(self) -> None:
        dialog = UpdaterRunnerDialog()
        try:
            self.assertEqual(dialog.windowTitle(), "OrderScout Updater")
            self.assertEqual(dialog.width(), 460)
            self.assertEqual(dialog.height(), 238)
            self.assertFalse(dialog._bar.isTextVisible())
            self.assertEqual(dialog._badge.text(), "Kurulum sürüyor")
        finally:
            dialog.allow_close(True)
            dialog.close()

    def test_runner_dialog_updates_stage_detail_and_progress(self) -> None:
        dialog = UpdaterRunnerDialog()
        try:
            dialog.set_stage("Dosyalar yerleştiriliyor...")
            dialog.set_detail("Adım: Installing the file.")
            dialog.set_progress(67)
            dialog.set_badge("Tamamlandı", kind="ok")

            self.assertEqual(dialog._stage.text(), "Dosyalar yerleştiriliyor...")
            self.assertEqual(dialog._detail.text(), "Adım: Installing the file.")
            self.assertEqual(dialog._bar.value(), 67)
            self.assertEqual(dialog._badge.text(), "Tamamlandı")
        finally:
            dialog.allow_close(True)
            dialog.close()

    def test_installer_failure_rolls_back_before_relaunching_previous_runtime(self) -> None:
        class DummyDialog:
            def set_badge(self, *_args, **_kwargs):
                pass

            def set_stage(self, *_args, **_kwargs):
                pass

            def set_detail(self, *_args, **_kwargs):
                pass

            def set_progress(self, *_args, **_kwargs):
                pass

            def allow_close(self, *_args, **_kwargs):
                pass

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_exe = root / "os-0.1.0" / "OrderScout.exe"
            new_exe = root / "os-0.2.0" / "OrderScout.exe"
            runner_state = root / "runner_state.json"
            old_exe.parent.mkdir(parents=True, exist_ok=True)
            new_exe.parent.mkdir(parents=True, exist_ok=True)
            old_exe.write_bytes(b"old")
            new_exe.write_bytes(b"new")
            controller = InstallerRunnerController.__new__(InstallerRunnerController)
            controller._dialog = DummyDialog()
            controller._runner_state = runner_state
            controller._previous_exe = old_exe
            controller._target_exe = new_exe
            launched: list[str] = []
            controller._launch_path = lambda path: launched.append(str(path)) or None

            with patch("Update.processors.pipeline.rollback_installed_update") as mocked_rollback, patch.object(
                runner_app.QTimer,
                "singleShot",
                return_value=None,
            ):
                mocked_rollback.return_value = Result.ok(
                    close_dialog=False,
                    data={"rollback_exe": str(old_exe)},
                )
                controller._finish_failure("installer failed")

            self.assertEqual(launched, [str(old_exe)])
            kwargs = mocked_rollback.call_args.kwargs
            self.assertEqual(str(kwargs.get("reason")), "installer_failed")
            self.assertTrue(bool(kwargs.get("notify_user")))
            runner_payload = json.loads(runner_state.read_text(encoding="utf-8"))
            self.assertEqual(runner_payload.get("status"), "failed")

    def test_target_exit_zero_before_prompt_is_treated_as_startup_failure(self) -> None:
        class DummyTimer:
            def stop(self):
                pass

        class ExitedProcess:
            def poll(self):
                return 0

        controller = InstallerRunnerController.__new__(InstallerRunnerController)
        controller._target_proc = ExitedProcess()
        controller._target_watch_timer = DummyTimer()
        captured: dict[str, object] = {}
        controller._finish_target_startup_failure = lambda **kwargs: captured.update(kwargs)

        controller._poll_target_startup()

        self.assertEqual(captured.get("exit_code"), 0)
        self.assertEqual(captured.get("reason"), "target_exited_before_decision")


if __name__ == "__main__":
    unittest.main()
