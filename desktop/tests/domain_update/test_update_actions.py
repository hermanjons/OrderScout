from __future__ import annotations

import unittest
from unittest.mock import patch

from Feedback.processors.pipeline import Result
import Update.views.actions as update_actions


class TestUpdateActions(unittest.TestCase):
    def test_download_finish_waits_for_ok_before_launching_installer(self) -> None:
        controller = update_actions.UpdateController(parent=None)
        events: list[str] = []
        result = Result.ok(close_dialog=False, data={"plan": {"kind": "installer_exe"}})

        def _info(*_args, **_kwargs):
            events.append("info")
            return None

        def _launch(_plan):
            events.append("launch")
            return Result.ok(close_dialog=False)

        with patch.object(update_actions, "is_runtime_updatable", return_value=True), patch.object(
            update_actions.AppMessageCenter,
            "info",
            side_effect=_info,
        ), patch.object(
            update_actions,
            "launch_prepared_update",
            side_effect=_launch,
        ):
            controller._on_download_finished(result)

        self.assertEqual(events, ["info", "launch"])

    def test_process_post_update_startup_skips_redirect_in_non_frozen_runtime(self) -> None:
        controller = update_actions.UpdateController(parent=None)
        startup_res = Result.ok(
            close_dialog=False,
            data={"action": "redirect", "target_exe": r"D:\OrderScout\os-0.1.3\OrderScout.exe", "state": {}},
        )

        with patch.object(update_actions, "evaluate_update_startup_state", return_value=startup_res), patch.object(
            controller,
            "_launch_executable",
            return_value=True,
        ) as mocked_launch:
            controller.process_post_update_startup()

        self.assertEqual(mocked_launch.call_count, 0)

    def test_process_post_update_startup_accepts_and_cleans_without_second_prompt(self) -> None:
        controller = update_actions.UpdateController(parent=None)
        startup_res = Result.ok(
            close_dialog=False,
            data={"action": "prompt_decision", "state": {"release_version": "0.1.4"}},
        )

        with patch.object(update_actions, "evaluate_update_startup_state", return_value=startup_res), patch.object(
            update_actions.AppMessageCenter,
            "confirm",
            return_value=True,
        ) as mocked_confirm, patch.object(
            update_actions,
            "mark_update_decision_prompt_shown",
            return_value=Result.ok(close_dialog=False),
        ) as mocked_prompt_marker, patch.object(
            update_actions,
            "accept_installed_update",
            return_value=Result.ok(close_dialog=False, data={"removed_previous": True}),
        ) as mocked_accept, patch.object(
            update_actions.AppMessageCenter,
            "info",
            return_value=None,
        ):
            controller.process_post_update_startup()

        self.assertEqual(mocked_confirm.call_count, 1)
        self.assertEqual(mocked_prompt_marker.call_count, 1)
        self.assertEqual(mocked_accept.call_count, 1)
        kwargs = mocked_accept.call_args.kwargs
        self.assertTrue(bool(kwargs.get("cleanup_previous")))

    def test_process_post_update_startup_falls_back_to_accept_without_cleanup(self) -> None:
        controller = update_actions.UpdateController(parent=None)
        startup_res = Result.ok(
            close_dialog=False,
            data={"action": "prompt_decision", "state": {"release_version": "0.1.4"}},
        )

        with patch.object(update_actions, "evaluate_update_startup_state", return_value=startup_res), patch.object(
            update_actions.AppMessageCenter,
            "confirm",
            return_value=True,
        ), patch.object(
            update_actions,
            "mark_update_decision_prompt_shown",
            return_value=Result.ok(close_dialog=False),
        ), patch.object(
            update_actions,
            "accept_installed_update",
            side_effect=[
                Result.fail("cleanup failed", close_dialog=False),
                Result.ok(close_dialog=False, data={"removed_previous": False}),
            ],
        ) as mocked_accept, patch.object(
            update_actions.AppMessageCenter,
            "warning",
            return_value=None,
        ) as mocked_warning:
            controller.process_post_update_startup()

        self.assertEqual(mocked_accept.call_count, 2)
        first_kwargs = mocked_accept.call_args_list[0].kwargs
        second_kwargs = mocked_accept.call_args_list[1].kwargs
        self.assertTrue(bool(first_kwargs.get("cleanup_previous")))
        self.assertFalse(bool(second_kwargs.get("cleanup_previous")))
        self.assertEqual(mocked_warning.call_count, 1)

    def test_process_post_update_startup_notifies_auto_rollback_once(self) -> None:
        controller = update_actions.UpdateController(parent=None)
        startup_res = Result.ok(
            close_dialog=False,
            data={
                "action": "notify_rollback",
                "state": {
                    "release_version": "0.3.1",
                    "rollback_reason": "target_crashed_before_decision",
                },
            },
        )

        with patch.object(update_actions, "evaluate_update_startup_state", return_value=startup_res), patch.object(
            update_actions.AppMessageCenter,
            "warning",
            return_value=None,
        ) as mocked_warning, patch.object(
            update_actions,
            "mark_update_rollback_notice_seen",
            return_value=Result.ok(close_dialog=False),
        ) as mocked_notice, patch.object(
            update_actions,
            "clear_update_state",
            return_value=Result.ok(close_dialog=False),
        ) as mocked_clear:
            controller.process_post_update_startup()

        self.assertEqual(mocked_warning.call_count, 1)
        self.assertEqual(mocked_notice.call_count, 1)
        self.assertEqual(mocked_clear.call_count, 1)

    def test_process_post_update_startup_auto_rolls_back_before_redirect_loop(self) -> None:
        controller = update_actions.UpdateController(parent=None)
        startup_res = Result.ok(
            close_dialog=False,
            data={
                "action": "auto_rollback",
                "reason": "target_prompt_not_reached",
                "target_exe": r"D:\OrderScout\os-0.3.1\OrderScout.exe",
                "state": {"release_version": "0.3.1"},
            },
        )

        with patch.object(update_actions, "evaluate_update_startup_state", return_value=startup_res), patch.object(
            update_actions,
            "rollback_installed_update",
            return_value=Result.ok(close_dialog=False, data={"rollback_exe": r"D:\OrderScout\OrderScout.exe"}),
        ) as mocked_rollback, patch.object(
            update_actions.AppMessageCenter,
            "warning",
            return_value=None,
        ) as mocked_warning, patch.object(
            update_actions,
            "mark_update_rollback_notice_seen",
            return_value=Result.ok(close_dialog=False),
        ), patch.object(
            update_actions,
            "clear_update_state",
            return_value=Result.ok(close_dialog=False),
        ):
            controller.process_post_update_startup()

        self.assertEqual(mocked_warning.call_count, 1)
        kwargs = mocked_rollback.call_args.kwargs
        self.assertTrue(bool(kwargs.get("notify_user")))
        self.assertEqual(str(kwargs.get("reason")), "target_prompt_not_reached")


if __name__ == "__main__":
    unittest.main()
