from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Feedback.processors.pipeline import Result
import Update.processors.pipeline as update_pipeline


class TestUpdatePipeline(unittest.TestCase):
    def _fake_release(self) -> dict:
        return {
            "tag_name": "v0.2.0",
            "name": "OrderScout v0.2.0",
            "body": "Release notes",
            "assets": [
                {
                    "name": "OrderScout-portable.zip",
                    "download_url": "https://example.test/portable.zip",
                    "size": 123456,
                },
                {
                    "name": "OrderScout-setup.exe",
                    "download_url": "https://example.test/setup.exe",
                    "size": 223456,
                },
            ],
        }

    def _fake_config(self, *, channel: str = "stable", require_sha256: bool = True) -> dict:
        return {
            "enabled": True,
            "channel": channel,
            "check_on_startup": True,
            "startup_delay_ms": 3000,
            "provider": "github",
            "github": {
                "owner": "demo",
                "repo": "demo",
                "api_base": "https://api.github.com",
                "include_prerelease": False,
            },
            "request": {
                "timeout_sec": 20,
                "retry_count": 3,
                "retry_backoff_sec": 0.1,
            },
            "dev": {
                "allow_non_frozen_apply": False,
            },
            "integrity": {
                "require_sha256": require_sha256,
            },
            "asset": {
                "prefer_extensions": [".exe"],
                "name_contains": ["orderscout"],
                "exclude_contains": [".blockmap", ".sig", ".sha256"],
            },
        }

    def test_select_release_asset_prefers_installer_exe(self) -> None:
        release = self._fake_release()
        chosen = update_pipeline.select_release_asset(release)
        self.assertIsNotNone(chosen)
        self.assertTrue(str(chosen.get("name")).lower().endswith(".exe"))

    def test_select_release_asset_ignores_excluded_artifacts(self) -> None:
        release = {
            "assets": [
                {"name": "OrderScout.blockmap", "download_url": "https://example.test/app.blockmap"},
                {"name": "OrderScout.sig", "download_url": "https://example.test/app.sig"},
                {"name": "OrderScout-portable.zip", "download_url": "https://example.test/app.zip"},
                {"name": "OrderScout-setup.exe", "download_url": "https://example.test/app.exe"},
            ]
        }
        chosen = update_pipeline.select_release_asset(release)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.get("name"), "OrderScout-setup.exe")

    def test_select_release_asset_rejects_zip_only_release(self) -> None:
        release = {
            "assets": [
                {"name": "OrderScout-portable.zip", "download_url": "https://example.test/app.zip"},
            ]
        }
        chosen = update_pipeline.select_release_asset(release)
        self.assertIsNone(chosen)

    def test_parse_bool_text_supports_common_env_values(self) -> None:
        self.assertTrue(update_pipeline._parse_bool_text("enabled"))
        self.assertFalse(update_pipeline._parse_bool_text("OFF"))
        self.assertIsNone(update_pipeline._parse_bool_text("maybe"))

    def test_normalize_sha256_text_rejects_malformed_digest(self) -> None:
        self.assertEqual(update_pipeline._normalize_sha256_text("sha256:" + ("c" * 64)), "c" * 64)
        self.assertEqual(update_pipeline._normalize_sha256_text("sha256:xyz"), "")

    def test_check_for_updates_available_when_newer_release_exists(self) -> None:
        release = self._fake_release()
        with patch.object(
            update_pipeline,
            "fetch_latest_release",
            return_value=Result.ok(close_dialog=False, data={"release": release}),
        ):
            res = update_pipeline.check_for_updates(current_version="0.1.0")

        self.assertTrue(res.success, res.message)
        data = res.data or {}
        self.assertTrue(bool(data.get("available")))
        self.assertEqual(str(data.get("latest_version")), "0.2.0")
        self.assertEqual(str((data.get("selected_asset") or {}).get("name")), "OrderScout-setup.exe")

    def test_check_for_updates_not_available_when_same_version(self) -> None:
        release = self._fake_release()
        with patch.object(
            update_pipeline,
            "fetch_latest_release",
            return_value=Result.ok(close_dialog=False, data={"release": release}),
        ):
            res = update_pipeline.check_for_updates(current_version="0.2.0")

        self.assertTrue(res.success, res.message)
        data = res.data or {}
        self.assertFalse(bool(data.get("available")))
        self.assertIsNone(data.get("selected_asset"))

    def test_is_newer_version_handles_prerelease_progression(self) -> None:
        self.assertTrue(update_pipeline._is_newer_version("0.2.0-beta.1", "0.2.0-beta.2"))
        self.assertFalse(update_pipeline._is_newer_version("0.2.0-beta.2", "0.2.0-beta.1"))

    def test_is_newer_version_prefers_stable_over_same_core_prerelease(self) -> None:
        self.assertTrue(update_pipeline._is_newer_version("0.2.0-beta.5", "0.2.0"))
        self.assertFalse(update_pipeline._is_newer_version("0.2.0", "0.2.0-beta.5"))

    def test_check_for_updates_with_prerelease_release(self) -> None:
        release = self._fake_release()
        release["tag_name"] = "v0.2.0-beta.2"
        release["name"] = "OrderScout v0.2.0-beta.2"
        with patch.object(
            update_pipeline,
            "fetch_latest_release",
            return_value=Result.ok(close_dialog=False, data={"release": release}),
        ):
            res = update_pipeline.check_for_updates(current_version="0.2.0-beta.1")

        self.assertTrue(res.success, res.message)
        data = res.data or {}
        self.assertTrue(bool(data.get("available")))
        self.assertEqual(str(data.get("latest_version")), "0.2.0-beta.2")

    def test_beta_current_version_forces_prerelease_fetch(self) -> None:
        with patch.object(
            update_pipeline,
            "fetch_latest_release",
            return_value=Result.fail("mock", close_dialog=False),
        ) as mocked_fetch:
            update_pipeline.check_for_updates(current_version="0.2.0-beta.1")

        self.assertIsNotNone(mocked_fetch.call_args)
        kwargs = mocked_fetch.call_args.kwargs
        self.assertTrue(bool(kwargs.get("include_prerelease")))

    def test_beta_channel_forces_prerelease_fetch_for_stable_current(self) -> None:
        cfg = self._fake_config(channel="beta")
        with patch.object(update_pipeline, "load_update_config", return_value=cfg), patch.object(
            update_pipeline,
            "fetch_latest_release",
            return_value=Result.fail("mock", close_dialog=False),
        ) as mocked_fetch:
            update_pipeline.check_for_updates(current_version="0.2.0")

        self.assertIsNotNone(mocked_fetch.call_args)
        kwargs = mocked_fetch.call_args.kwargs
        self.assertTrue(bool(kwargs.get("include_prerelease")))

    def test_asset_expected_sha256_parses_digest(self) -> None:
        digest = "sha256:" + ("a" * 64)
        value = update_pipeline._asset_expected_sha256({"digest": digest})
        self.assertEqual(value, "a" * 64)

    def test_download_prepare_requires_sha256_when_enabled(self) -> None:
        cfg = self._fake_config(require_sha256=True)
        release = self._fake_release()
        asset = {
            "name": "OrderScout_Setup_x64.exe",
            "download_url": "https://example.test/OrderScout_Setup_x64.exe",
            "size": 10,
        }
        with patch.object(update_pipeline, "load_update_config", return_value=cfg), patch.object(
            update_pipeline,
            "_download_asset",
        ) as mocked_download:
            res = update_pipeline.download_and_prepare_update(release=release, asset=asset)

        self.assertFalse(res.success)
        self.assertIn("SHA256", str(res.message))
        mocked_download.assert_not_called()

    def test_download_prepare_rejects_zip_without_download(self) -> None:
        cfg = self._fake_config(require_sha256=False)
        release = self._fake_release()
        asset = {
            "name": "OrderScout-portable.zip",
            "download_url": "https://example.test/OrderScout-portable.zip",
            "size": 10,
        }
        with patch.object(update_pipeline, "load_update_config", return_value=cfg), patch.object(
            update_pipeline,
            "_download_asset",
        ) as mocked_download:
            res = update_pipeline.download_and_prepare_update(release=release, asset=asset)

        self.assertFalse(res.success)
        self.assertEqual((res.data or {}).get("unsupported_asset_kind"), "portable_zip")
        mocked_download.assert_not_called()

    def test_download_prepare_rejects_asset_name_with_path_separator(self) -> None:
        cfg = self._fake_config(require_sha256=False)
        release = self._fake_release()
        asset = {
            "name": "../OrderScout_Setup_x64.exe",
            "download_url": "https://example.test/OrderScout_Setup_x64.exe",
            "size": 10,
        }
        with patch.object(update_pipeline, "load_update_config", return_value=cfg), patch.object(
            update_pipeline,
            "_download_asset",
        ) as mocked_download:
            res = update_pipeline.download_and_prepare_update(release=release, asset=asset)

        self.assertFalse(res.success)
        self.assertIn("asset name", str(res.message).lower())
        mocked_download.assert_not_called()

    def test_download_asset_removes_partial_file_after_stream_failure(self) -> None:
        class BrokenResponse:
            status_code = 200
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def iter_content(self, chunk_size: int):
                yield b"partial"
                raise RuntimeError("network dropped")

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "OrderScout_Setup_x64.exe"
            target.write_bytes(b"old")
            with patch.object(update_pipeline.requests, "get", return_value=BrokenResponse()):
                res = update_pipeline._download_asset(
                    asset={"download_url": "https://example.test/setup.exe"},
                    target_path=target,
                    timeout_sec=5,
                    retry_count=1,
                )

            self.assertFalse(res.success)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(f"{target.name}.part").exists())

    def test_download_prepare_passes_expected_sha_to_download(self) -> None:
        cfg = self._fake_config(require_sha256=True)
        release = self._fake_release()
        digest = "sha256:" + ("b" * 64)
        asset = {
            "name": "OrderScout_Setup_x64.exe",
            "download_url": "https://example.test/OrderScout_Setup_x64.exe",
            "size": 10,
            "digest": digest,
        }
        fake_download_res = Result.ok(
            close_dialog=False,
            data={"path": "x", "bytes": 10, "sha256": "b" * 64},
        )
        with patch.object(update_pipeline, "load_update_config", return_value=cfg), patch.object(
            update_pipeline,
            "_download_asset",
            return_value=fake_download_res,
        ) as mocked_download:
            res = update_pipeline.download_and_prepare_update(release=release, asset=asset)

        self.assertTrue(res.success, res.message)
        plan = (res.data or {}).get("plan") or {}
        self.assertEqual(str(plan.get("kind")), "installer_exe")
        self.assertTrue(bool(str(plan.get("runner_payload") or "").strip()))
        self.assertTrue(bool(str(plan.get("target_install_dir") or "").strip()))
        self.assertTrue(bool(str(plan.get("target_exe") or "").strip()))
        self.assertIsNotNone(mocked_download.call_args)
        kwargs = mocked_download.call_args.kwargs
        self.assertEqual(str(kwargs.get("expected_sha256")), "b" * 64)

    def test_write_installer_runner_payload_serializes_expected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            installer = root / "setup.exe"
            target_dir = root / "os-0.2.0"
            installer_log = root / "installer.log"
            runner_state = root / "runner_state.json"
            target_exe = target_dir / "OrderScout.exe"
            previous_exe = root / "os-0.1.0" / "OrderScout.exe"
            payload_path = root / "runner_payload.json"

            installer.write_bytes(b"x")
            target_exe.parent.mkdir(parents=True, exist_ok=True)
            previous_exe.parent.mkdir(parents=True, exist_ok=True)
            target_exe.write_bytes(b"new")
            previous_exe.write_bytes(b"old")

            res = update_pipeline._write_installer_runner_payload(
                installer_path=installer,
                target_dir=target_dir,
                installer_log=installer_log,
                runner_state_path=runner_state,
                target_exe=target_exe,
                previous_exe=previous_exe,
                payload_path=payload_path,
                release_version="0.2.0",
            )

            self.assertTrue(res.success, res.message)
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("release_version")), "0.2.0")
            self.assertEqual(str(payload.get("installer_path")), str(installer.resolve()))
            self.assertEqual(str(payload.get("target_exe")), str(target_exe.resolve()))

    def test_write_windows_apply_script_includes_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_dir = root / "src"
            install_dir = root / "dst"
            backup_dir = root / "backup"
            script_path = root / "apply_update.cmd"
            source_dir.mkdir(parents=True, exist_ok=True)
            install_dir.mkdir(parents=True, exist_ok=True)

            res = update_pipeline._write_windows_apply_script(
                source_dir=source_dir,
                install_dir=install_dir,
                backup_dir=backup_dir,
                exe_name="OrderScout.exe",
                script_path=script_path,
            )

            self.assertTrue(res.success, res.message)
            self.assertTrue(script_path.exists())
            text = script_path.read_text(encoding="utf-8")
            self.assertIn("creating backup", text)
            self.assertIn("rolling back previous version", text)

    def test_resolve_version_slot_uses_parent_for_versioned_current_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current = root / "os-0.1.0"
            current.mkdir(parents=True, exist_ok=True)
            target_dir, target_exe = update_pipeline._resolve_version_slot(
                current_install_dir=current,
                release_version="0.2.0",
                exe_name="OrderScout.exe",
            )
            self.assertEqual(target_dir, root / "os-0.2.0")
            self.assertEqual(target_exe, root / "os-0.2.0" / "OrderScout.exe")

    def test_evaluate_update_startup_state_prompts_on_target_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            old_exe = root / "os-0.1.0" / "OrderScout.exe"
            new_exe = root / "os-0.2.0" / "OrderScout.exe"
            old_exe.parent.mkdir(parents=True, exist_ok=True)
            new_exe.parent.mkdir(parents=True, exist_ok=True)
            old_exe.write_bytes(b"old")
            new_exe.write_bytes(b"new")
            with patch.object(update_pipeline, "UPDATE_STATE_FILE", state_file):
                update_pipeline._save_update_state(
                    {
                        "status": "pending_install",
                        "from_exe": str(old_exe),
                        "target_exe": str(new_exe),
                        "release_version": "0.2.0",
                    }
                )
                res = update_pipeline.evaluate_update_startup_state(current_exe=str(new_exe))
                state_after = update_pipeline._load_update_state()

            self.assertTrue(res.success, res.message)
            self.assertEqual((res.data or {}).get("action"), "prompt_decision")
            self.assertEqual(str(state_after.get("status")), "await_decision")
            self.assertEqual(int(state_after.get("target_start_attempts") or 0), 1)

    def test_begin_installer_update_state_replaces_stale_decision_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            old_exe = root / "os-0.1.0" / "OrderScout.exe"
            new_exe = root / "os-0.2.0" / "OrderScout.exe"
            with patch.object(update_pipeline, "UPDATE_STATE_FILE", state_file):
                update_pipeline._save_update_state(
                    {
                        "status": "rolled_back",
                        "from_exe": "old",
                        "target_exe": "bad",
                        "decision_prompt_shown_at": "2026-05-09T00:00:00Z",
                        "target_launch_attempted_at": "2026-05-09T00:00:01Z",
                        "target_launch_attempts": 3,
                        "notify_user": True,
                        "rollback_reason": "target_crashed_before_decision",
                    }
                )
                update_pipeline._begin_installer_update_state(
                    release_version="0.2.0",
                    workspace=str(root),
                    from_exe=str(old_exe),
                    target_exe=str(new_exe),
                )
                state_after = update_pipeline._load_update_state()

            self.assertEqual(str(state_after.get("status")), "pending_install")
            self.assertEqual(str(state_after.get("from_exe")), str(old_exe))
            self.assertEqual(str(state_after.get("target_exe")), str(new_exe))
            self.assertNotIn("decision_prompt_shown_at", state_after)
            self.assertNotIn("target_launch_attempted_at", state_after)
            self.assertNotIn("target_launch_attempts", state_after)
            self.assertNotIn("notify_user", state_after)
            self.assertNotIn("rollback_reason", state_after)

    def test_mark_update_decision_prompt_shown_records_prompt_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            old_exe = root / "os-0.1.0" / "OrderScout.exe"
            new_exe = root / "os-0.2.0" / "OrderScout.exe"
            old_exe.parent.mkdir(parents=True, exist_ok=True)
            new_exe.parent.mkdir(parents=True, exist_ok=True)
            old_exe.write_bytes(b"old")
            new_exe.write_bytes(b"new")
            with patch.object(update_pipeline, "UPDATE_STATE_FILE", state_file):
                update_pipeline._save_update_state(
                    {
                        "status": "await_decision",
                        "from_exe": str(old_exe),
                        "target_exe": str(new_exe),
                        "release_version": "0.2.0",
                    }
                )
                res = update_pipeline.mark_update_decision_prompt_shown(current_exe=str(new_exe))
                state_after = update_pipeline._load_update_state()

            self.assertTrue(res.success, res.message)
            self.assertTrue(str(state_after.get("decision_prompt_shown_at") or "").strip())

    def test_evaluate_update_startup_state_auto_rolls_back_when_prompt_never_showed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            old_exe = root / "os-0.1.0" / "OrderScout.exe"
            new_exe = root / "os-0.2.0" / "OrderScout.exe"
            old_exe.parent.mkdir(parents=True, exist_ok=True)
            new_exe.parent.mkdir(parents=True, exist_ok=True)
            old_exe.write_bytes(b"old")
            new_exe.write_bytes(b"new")
            with patch.object(update_pipeline, "UPDATE_STATE_FILE", state_file):
                update_pipeline._save_update_state(
                    {
                        "status": "pending_install",
                        "from_exe": str(old_exe),
                        "target_exe": str(new_exe),
                        "release_version": "0.2.0",
                        "target_launch_attempted_at": "2026-05-09T00:00:00Z",
                        "target_launch_attempts": 1,
                    }
                )
                res = update_pipeline.evaluate_update_startup_state(current_exe=str(old_exe))

            self.assertTrue(res.success, res.message)
            self.assertEqual((res.data or {}).get("action"), "auto_rollback")
            self.assertEqual((res.data or {}).get("target_exe"), str(new_exe))

    def test_mark_update_target_launch_attempted_records_launch_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            old_exe = root / "os-0.1.0" / "OrderScout.exe"
            new_exe = root / "os-0.2.0" / "OrderScout.exe"
            old_exe.parent.mkdir(parents=True, exist_ok=True)
            new_exe.parent.mkdir(parents=True, exist_ok=True)
            old_exe.write_bytes(b"old")
            new_exe.write_bytes(b"new")
            with patch.object(update_pipeline, "UPDATE_STATE_FILE", state_file):
                update_pipeline._save_update_state(
                    {
                        "status": "pending_install",
                        "from_exe": str(old_exe),
                        "target_exe": str(new_exe),
                        "release_version": "0.2.0",
                    }
                )
                res = update_pipeline.mark_update_target_launch_attempted(target_exe=str(new_exe))
                state_after = update_pipeline._load_update_state()

            self.assertTrue(res.success, res.message)
            self.assertTrue(str(state_after.get("target_launch_attempted_at") or "").strip())
            self.assertEqual(int(state_after.get("target_launch_attempts") or 0), 1)

    def test_accept_installed_update_marks_state_and_cleans_old_version_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            old_exe = root / "os-0.1.0" / "OrderScout.exe"
            new_exe = root / "os-0.2.0" / "OrderScout.exe"
            old_exe.parent.mkdir(parents=True, exist_ok=True)
            new_exe.parent.mkdir(parents=True, exist_ok=True)
            old_exe.write_bytes(b"old")
            new_exe.write_bytes(b"new")
            with patch.object(update_pipeline, "UPDATE_STATE_FILE", state_file):
                update_pipeline._save_update_state(
                    {
                        "status": "await_decision",
                        "from_exe": str(old_exe),
                        "target_exe": str(new_exe),
                        "release_version": "0.2.0",
                    }
                )
                res = update_pipeline.accept_installed_update(
                    current_exe=str(new_exe),
                    cleanup_previous=True,
                )
                state_after = update_pipeline._load_update_state()

            self.assertTrue(res.success, res.message)
            self.assertEqual(str(state_after.get("status")), "accepted")
            self.assertFalse(old_exe.parent.exists())

    def test_accept_installed_update_cleans_root_runtime_payload_but_keeps_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            old_exe = root / "OrderScout.exe"
            old_internal = root / "_internal"
            old_unins_exe = root / "unins000.exe"
            old_unins_dat = root / "unins000.dat"
            old_outputs = root / "outputs"
            keep_file = root / "notes.txt"
            new_exe = root / "os-0.2.0" / "OrderScout.exe"

            old_internal.mkdir(parents=True, exist_ok=True)
            old_outputs.mkdir(parents=True, exist_ok=True)
            new_exe.parent.mkdir(parents=True, exist_ok=True)
            old_exe.write_bytes(b"old")
            old_unins_exe.write_bytes(b"u")
            old_unins_dat.write_bytes(b"d")
            (old_internal / "x.bin").write_bytes(b"x")
            (old_outputs / "report.txt").write_text("old-output", encoding="utf-8")
            keep_file.write_text("keep", encoding="utf-8")
            new_exe.write_bytes(b"new")

            with patch.object(update_pipeline, "UPDATE_STATE_FILE", state_file):
                update_pipeline._save_update_state(
                    {
                        "status": "await_decision",
                        "from_exe": str(old_exe),
                        "target_exe": str(new_exe),
                        "release_version": "0.2.0",
                    }
                )
                res = update_pipeline.accept_installed_update(
                    current_exe=str(new_exe),
                    cleanup_previous=True,
                )
                state_after = update_pipeline._load_update_state()

            self.assertTrue(res.success, res.message)
            self.assertEqual(str(state_after.get("status")), "accepted")
            self.assertFalse(old_exe.exists())
            self.assertFalse(old_internal.exists())
            self.assertFalse(old_unins_exe.exists())
            self.assertFalse(old_unins_dat.exists())
            self.assertTrue(old_outputs.exists())
            self.assertTrue(keep_file.exists())
            self.assertTrue(new_exe.exists())

    def test_rollback_installed_update_removes_target_version_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            old_exe = root / "os-0.1.0" / "OrderScout.exe"
            new_exe = root / "os-0.2.0" / "OrderScout.exe"
            old_exe.parent.mkdir(parents=True, exist_ok=True)
            new_exe.parent.mkdir(parents=True, exist_ok=True)
            old_exe.write_bytes(b"old")
            new_exe.write_bytes(b"new")
            with patch.object(update_pipeline, "UPDATE_STATE_FILE", state_file):
                update_pipeline._save_update_state(
                    {
                        "status": "await_decision",
                        "from_exe": str(old_exe),
                        "target_exe": str(new_exe),
                        "release_version": "0.2.0",
                    }
                )
                res = update_pipeline.rollback_installed_update(current_exe=str(new_exe))
                state_after = update_pipeline._load_update_state()

            self.assertTrue(res.success, res.message)
            self.assertEqual(str(state_after.get("status")), "rolled_back")
            self.assertFalse(new_exe.parent.exists())
            self.assertEqual(str((res.data or {}).get("rollback_exe")), str(old_exe))

    def test_rollback_installed_update_can_notify_old_runtime_after_crash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            old_exe = root / "os-0.1.0" / "OrderScout.exe"
            new_exe = root / "os-0.2.0" / "OrderScout.exe"
            old_exe.parent.mkdir(parents=True, exist_ok=True)
            new_exe.parent.mkdir(parents=True, exist_ok=True)
            old_exe.write_bytes(b"old")
            new_exe.write_bytes(b"new")
            with patch.object(update_pipeline, "UPDATE_STATE_FILE", state_file):
                update_pipeline._save_update_state(
                    {
                        "status": "pending_install",
                        "from_exe": str(old_exe),
                        "target_exe": str(new_exe),
                        "release_version": "0.2.0",
                    }
                )
                rollback_res = update_pipeline.rollback_installed_update(
                    current_exe=str(new_exe),
                    reason="target_crashed_before_decision",
                    notify_user=True,
                    exit_code=-1073740791,
                )
                state_after = update_pipeline._load_update_state()
                eval_res = update_pipeline.evaluate_update_startup_state(current_exe=str(old_exe))

            self.assertTrue(rollback_res.success, rollback_res.message)
            self.assertEqual(str(state_after.get("status")), "rolled_back")
            self.assertTrue(bool(state_after.get("notify_user")))
            self.assertEqual(str(state_after.get("rollback_reason")), "target_crashed_before_decision")
            self.assertEqual(int(state_after.get("failed_target_exit_code") or 0), -1073740791)
            self.assertEqual((eval_res.data or {}).get("action"), "notify_rollback")

    def test_resolve_safe_zip_member_path_allows_relative_member(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = update_pipeline._resolve_safe_zip_member_path(root, "app/OrderScout.exe")
            target.relative_to(root.resolve())  # should not raise

    def test_resolve_safe_zip_member_path_blocks_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(RuntimeError):
                update_pipeline._resolve_safe_zip_member_path(root, "../evil.exe")

    def test_write_windows_installer_runner_script_includes_modern_ui_and_ascii_sanitizer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            installer = root / "setup.exe"
            target_dir = root / "os-0.2.0"
            installer_log = root / "installer.log"
            runner_state = root / "runner_state.json"
            target_exe = target_dir / "OrderScout.exe"
            previous_exe = root / "os-0.1.0" / "OrderScout.exe"
            script_path = root / "run_installer_ui.ps1"

            installer.write_bytes(b"x")
            target_exe.parent.mkdir(parents=True, exist_ok=True)
            previous_exe.parent.mkdir(parents=True, exist_ok=True)
            target_exe.write_bytes(b"new")
            previous_exe.write_bytes(b"old")

            res = update_pipeline._write_windows_installer_runner_script(
                installer_path=installer,
                target_dir=target_dir,
                installer_log=installer_log,
                runner_state_path=runner_state,
                target_exe=target_exe,
                previous_exe=previous_exe,
                script_path=script_path,
            )

            self.assertTrue(res.success, res.message)
            self.assertTrue(script_path.exists())
            body = script_path.read_text(encoding="utf-8-sig")
            self.assertIn("function To-Ascii", body)
            self.assertIn("function Set-UiProgress", body)
            self.assertIn("$form.FormBorderStyle = 'FixedSingle'", body)
            self.assertIn("$form.BackColor", body)
            self.assertIn("Set-UiProgress $pulse \"Adim: $cleanLine\" 'running'", body)
            self.assertIn("if ((-not $proc.HasExited) -and (-not $progressChanged))", body)

    def test_launch_prepared_update_starts_qt_runner_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            installer = root / "OrderScout_Setup_x64.exe"
            runner_payload = root / "runner_payload.json"
            runner_state = root / "runner_state.json"
            current_exe = root / "os-0.1.0" / "OrderScout.exe"
            installer.write_bytes(b"x")
            runner_payload.write_text("{}", encoding="utf-8")
            current_exe.parent.mkdir(parents=True, exist_ok=True)
            current_exe.write_bytes(b"old")

            plan = {
                "kind": "installer_exe",
                "installer_path": str(installer),
                "runner_payload": str(runner_payload),
                "runner_state": str(runner_state),
                "target_exe": str(root / "os-0.2.0" / "OrderScout.exe"),
                "target_install_dir": str(root / "os-0.2.0"),
                "current_exe": str(current_exe),
                "release_version": "0.2.0",
                "workspace": str(root),
            }

            with patch.object(update_pipeline.os, "name", "nt"), patch.object(
                update_pipeline,
                "_begin_installer_update_state",
            ), patch.object(
                update_pipeline,
                "_wait_for_runner_ready",
                return_value=True,
            ), patch.object(
                update_pipeline.subprocess,
                "Popen",
            ) as mocked_popen:
                res = update_pipeline.launch_prepared_update(plan)

            self.assertTrue(res.success, res.message)
            self.assertEqual(str((res.data or {}).get("mode")), "runner_ui")
            self.assertIsNotNone(mocked_popen.call_args)
            args = mocked_popen.call_args.args[0]
            kwargs = mocked_popen.call_args.kwargs
            self.assertIn("--update-runner", args)
            self.assertIn(str(runner_payload), args)
            self.assertTrue(str(args[0]).endswith("OrderScout.exe"))
            self.assertNotIn("creationflags", kwargs)

    def test_launch_prepared_update_rejects_portable_zip_plan(self) -> None:
        with patch.object(update_pipeline.os, "name", "nt"):
            res = update_pipeline.launch_prepared_update({"kind": "portable_zip", "apply_script": "x.cmd"})

        self.assertFalse(res.success)
        self.assertEqual((res.data or {}).get("unsupported_asset_kind"), "portable_zip")

    def test_launch_prepared_update_rejects_missing_installer_path(self) -> None:
        with patch.object(update_pipeline.os, "name", "nt"):
            res = update_pipeline.launch_prepared_update(
                {
                    "kind": "installer_exe",
                    "runner_payload": "payload.json",
                    "runner_state": "state.json",
                    "target_exe": "target.exe",
                    "target_install_dir": "target",
                    "current_exe": "current.exe",
                    "release_version": "0.2.0",
                    "workspace": "workspace",
                }
            )

        self.assertFalse(res.success)
        self.assertIn("path is missing", str(res.message))

    def test_launch_prepared_update_clears_state_when_runner_fails_to_start(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            installer = root / "OrderScout_Setup_x64.exe"
            runner_payload = root / "runner_payload.json"
            runner_state = root / "runner_state.json"
            current_exe = root / "os-0.1.0" / "OrderScout.exe"
            installer.write_bytes(b"x")
            runner_payload.write_text("{}", encoding="utf-8")
            current_exe.parent.mkdir(parents=True, exist_ok=True)
            current_exe.write_bytes(b"old")
            plan = {
                "kind": "installer_exe",
                "installer_path": str(installer),
                "runner_payload": str(runner_payload),
                "runner_state": str(runner_state),
                "target_exe": str(root / "os-0.2.0" / "OrderScout.exe"),
                "target_install_dir": str(root / "os-0.2.0"),
                "current_exe": str(current_exe),
                "release_version": "0.2.0",
                "workspace": str(root),
            }

            with patch.object(update_pipeline.os, "name", "nt"), patch.object(
                update_pipeline,
                "UPDATE_STATE_FILE",
                state_file,
            ), patch.object(
                update_pipeline.subprocess,
                "Popen",
                side_effect=OSError("boom"),
            ):
                res = update_pipeline.launch_prepared_update(plan)
                state_after = update_pipeline._load_update_state()

            self.assertFalse(res.success)
            self.assertEqual(state_after, {})

    def test_launch_prepared_update_keeps_state_when_runner_is_alive_but_not_ready_yet(self) -> None:
        class AliveProcess:
            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_file = root / "state.json"
            installer = root / "OrderScout_Setup_x64.exe"
            runner_payload = root / "runner_payload.json"
            runner_state = root / "runner_state.json"
            current_exe = root / "os-0.1.0" / "OrderScout.exe"
            installer.write_bytes(b"x")
            runner_payload.write_text("{}", encoding="utf-8")
            current_exe.parent.mkdir(parents=True, exist_ok=True)
            current_exe.write_bytes(b"old")
            plan = {
                "kind": "installer_exe",
                "installer_path": str(installer),
                "runner_payload": str(runner_payload),
                "runner_state": str(runner_state),
                "target_exe": str(root / "os-0.2.0" / "OrderScout.exe"),
                "target_install_dir": str(root / "os-0.2.0"),
                "current_exe": str(current_exe),
                "release_version": "0.2.0",
                "workspace": str(root),
            }

            with patch.object(update_pipeline.os, "name", "nt"), patch.object(
                update_pipeline,
                "UPDATE_STATE_FILE",
                state_file,
            ), patch.object(
                update_pipeline,
                "_wait_for_runner_ready",
                return_value=False,
            ), patch.object(
                update_pipeline.subprocess,
                "Popen",
                return_value=AliveProcess(),
            ):
                res = update_pipeline.launch_prepared_update(plan)
                state_after = update_pipeline._load_update_state()

            self.assertTrue(res.success, res.message)
            self.assertEqual(str((res.data or {}).get("mode")), "runner_ui_pending")
            self.assertEqual(str(state_after.get("status")), "pending_install")

    def test_is_runtime_updatable_false_on_non_windows(self) -> None:
        with patch.object(update_pipeline.os, "name", "posix"), patch.object(
            update_pipeline.sys,
            "frozen",
            False,
            create=True,
        ):
            self.assertFalse(update_pipeline.is_runtime_updatable())

    def test_is_runtime_updatable_true_when_frozen_on_windows(self) -> None:
        with patch.object(update_pipeline.os, "name", "nt"), patch.object(
            update_pipeline.sys,
            "frozen",
            True,
            create=True,
        ):
            self.assertTrue(update_pipeline.is_runtime_updatable())

    def test_is_runtime_updatable_true_with_dev_config_override(self) -> None:
        cfg = self._fake_config()
        cfg["dev"]["allow_non_frozen_apply"] = True
        with patch.object(update_pipeline.os, "name", "nt"), patch.object(
            update_pipeline.sys,
            "frozen",
            False,
            create=True,
        ), patch.dict(update_pipeline.os.environ, {"ORDER_SCOUT_UPDATE_DEV_APPLY": ""}, clear=False), patch.object(
            update_pipeline,
            "load_update_config",
            return_value=cfg,
        ):
            self.assertTrue(update_pipeline.is_runtime_updatable())

    def test_is_runtime_updatable_env_override_can_disable(self) -> None:
        cfg = self._fake_config()
        cfg["dev"]["allow_non_frozen_apply"] = True
        with patch.object(update_pipeline.os, "name", "nt"), patch.object(
            update_pipeline.sys,
            "frozen",
            False,
            create=True,
        ), patch.dict(update_pipeline.os.environ, {"ORDER_SCOUT_UPDATE_DEV_APPLY": "0"}, clear=False), patch.object(
            update_pipeline,
            "load_update_config",
            return_value=cfg,
        ):
            self.assertFalse(update_pipeline.is_runtime_updatable())

    def test_is_runtime_updatable_env_override_can_enable(self) -> None:
        cfg = self._fake_config()
        cfg["dev"]["allow_non_frozen_apply"] = False
        with patch.object(update_pipeline.os, "name", "nt"), patch.object(
            update_pipeline.sys,
            "frozen",
            False,
            create=True,
        ), patch.dict(update_pipeline.os.environ, {"ORDER_SCOUT_UPDATE_DEV_APPLY": "1"}, clear=False), patch.object(
            update_pipeline,
            "load_update_config",
            return_value=cfg,
        ):
            self.assertTrue(update_pipeline.is_runtime_updatable())


if __name__ == "__main__":
    unittest.main()
