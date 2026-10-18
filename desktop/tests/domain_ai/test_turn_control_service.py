from __future__ import annotations

import unittest
from copy import deepcopy
from unittest.mock import Mock

from AI.processors.session_state import AgentSessionState, PendingActionSnapshot, AgentTaskStep
from AI.processors.turn_service import approval_reply_protocol, run_typed_control_turn, resume_reply_interpretation
from Feedback.processors.pipeline import Result


class TestTurnControlService(unittest.TestCase):
    def test_resume_protocol_only_targets_a_nonterminal_existing_graph(self):
        state = AgentSessionState(goal="My read task", active_domain="general", status="interrupted")
        state.remaining_steps = [AgentTaskStep(index=1, prompt="Read", step_id="read")]
        self.assertEqual(resume_reply_interpretation("Devam et.", state)["mode"], "resume")
        self.assertIsNone(resume_reply_interpretation("Devam et ama önce raporu değiştir", state))
        state.status = "complete"
        self.assertIsNone(resume_reply_interpretation("Devam et", state))

    def test_resume_receipt_includes_only_steps_run_in_this_turn(self):
        prior = AgentTaskStep(index=1, prompt="Read", step_id="first", status="completed", tool_names=["orders.summary"], verification_status="observed")
        state = AgentSessionState(goal="My read task", active_domain="general", status="interrupted", completed_steps=[prior])
        next_step = AgentTaskStep(index=2, prompt="Next", step_id="second", status="completed", verification_status="observed", tool_names=["stock.inventory_overview"],
                                  result_data={"tool_result": {"active_items": 2}}, result_message="Stock observed")
        resumed = AgentSessionState.from_dict(state.to_dict())
        resumed.completed_steps.append(next_step)
        resumed.status = "complete"
        runner = Mock(return_value=Result.ok("Done", data={"state": resumed.to_dict(), "answer": "Done"}))
        result = run_typed_control_turn("devam et", mode="resume", session_state=state, client=None, db_name="isolated.db", resume_runner=runner)
        self.assertEqual(result.data["mode"], "resumed")
        self.assertEqual(result.data["tool_names"], ["stock.inventory_overview"])
        self.assertEqual(result.data["direct_tool_calls"][0]["step_id"], "second")
        self.assertEqual(result.data["state"]["conversation_turns"][-2]["mode"], "resume")
        self.assertEqual(len(state.completed_steps), 1)
        self.assertNotIn("approved_by", runner.call_args.kwargs)

    def _state(self):
        action = PendingActionSnapshot.refresh_identity({
            "action_type": "stock.action_create_manual_in_transaction",
            "status": "pending_approval", "approval_required": True, "execute_enabled": True,
            "arguments": {"payload": {"item_id": 12, "qty": 2}},
        })
        state = AgentSessionState(goal="Stok girişi", active_domain="stock", status="pending_approval")
        state.pending_actions = [action]
        state.active_pending_action_id = action["action_id"]
        state.active_entities["response_verifications"] = [{"source": "final_response", "allowed": False}]
        return state

    def test_long_replies_are_interpreted_instead_of_approving_by_a_word(self):
        for text in (
            "Tamam ama önce Excel'i göster", "Evet, yalnız ikinci ürünü değiştir",
            "Onayla dersem hangi kayıtları değiştireceksin?", "Olur, fakat bunu çalıştırma",
            "Önce iptal edilen siparişleri bul", "Kabul etmeden önce kârı kontrol et",
        ):
            with self.subTest(text=text):
                self.assertEqual(approval_reply_protocol(text), "")
        for text in ("Onayla ve çalıştır", "tamam onaylıyorum", "Çalıştır."):
            self.assertEqual(approval_reply_protocol(text), "approve")
        self.assertEqual(approval_reply_protocol("hayır iptal et"), "cancel")

    def test_artifact_confirmation_requires_matching_current_proposal(self):
        message = "Bu Excel dosyasının oluşturulmasını onaylıyorum."
        state = self._state()
        self.assertEqual(approval_reply_protocol(message), "")
        self.assertEqual(approval_reply_protocol(message, state), "")
        action = PendingActionSnapshot.refresh_identity({
            "action_type": "ai.action_export_report_snapshot_xlsx", "status": "pending_approval",
            "approval_required": True, "execute_enabled": True,
            "arguments": {"payload": {"output_path": "fixture.xlsx"}},
        })
        state.pending_actions = [action]
        state.active_pending_action_id = action["action_id"]
        self.assertEqual(approval_reply_protocol(message, state), "approve")
        for text in ("Bu Excel dosyasının oluşturulmasını onaylıyorum ama önce değiştir",
                     "Bu Excel dosyasının oluşturulmasını onaylıyor muyum?",
                     "Bu Excel dosyasının oluşturulmasını onaylamıyorum",
                     '"Bu Excel dosyasının oluşturulmasını onaylıyorum"',
                     "Önce bu Excel dosyasının oluşturulmasını onaylıyorum diye yaz"):
            with self.subTest(text=text):
                self.assertEqual(approval_reply_protocol(text, state), "")
        state.cancel_active_pending_action()
        self.assertEqual(approval_reply_protocol(message, state), "")

    def test_disabled_approval_preserves_exact_proposal_without_executor(self):
        state = self._state()
        before = deepcopy(state.to_dict())
        executor = Mock(side_effect=AssertionError("Unauthorized effect"))
        result = run_typed_control_turn(
            "onayla", mode="approve", session_state=state, client=None,
            db_name="unused.sqlite3", approval_runner=executor,
        )
        self.assertEqual(result.data["mode"], "approval_blocked")
        self.assertEqual(result.data["state"]["pending_actions"], before["pending_actions"])
        self.assertEqual(state.to_dict(), before)
        self.assertTrue(result.data["state"]["active_entities"]["response_verifications"][-1]["allowed"])
        executor.assert_not_called()

    def test_cancel_is_terminal_preserves_history_and_has_no_effect(self):
        state = self._state()
        state.remaining_steps = []
        executor = Mock(side_effect=AssertionError("Cancel executed"))
        result = run_typed_control_turn(
            "vazgeç", mode="cancel", session_state=state, client=None,
            db_name="unused.sqlite3", allow_approval_execute=True, approval_runner=executor,
        )
        after = result.data["state"]
        self.assertEqual(after["status"], "cancelled")
        self.assertEqual(after["active_pending_action_id"], "")
        self.assertEqual(after["pending_actions"], [])
        self.assertEqual(after["action_history"][-1]["phase"], "cancel")
        self.assertEqual([r["role"] for r in after["conversation_turns"]], ["user", "assistant"])
        executor.assert_not_called()
        self.assertEqual(state.status, "pending_approval")

    def test_stale_identity_cannot_execute_current_proposal(self):
        state = self._state()
        executor = Mock(side_effect=AssertionError("Stale identity executed"))
        result = run_typed_control_turn(
            "eski action_id 0a461f4c7c6adef0369cfa633fb955a7 onayla ve çalıştır",
            mode="approve", session_state=state, client=None, db_name="unused.sqlite3",
            allow_approval_execute=True, approval_runner=executor,
        )
        self.assertEqual(result.data["mode"], "stale_approval")
        self.assertEqual(result.data["state"]["active_pending_action_id"], state.active_pending_action_id)
        executor.assert_not_called()

    def test_approval_passes_exact_action_and_returns_current_execute_evidence(self):
        state = self._state()
        expected_id = state.active_pending_action_id
        after = AgentSessionState.from_dict(state.to_dict())
        after.resolve_pending_action(expected_id, status="executed", reason="fixture")
        after.status = "complete"
        executor = Mock(return_value=Result.ok("2 adet giriş doğrulandı.", data={
            "state": after.to_dict(), "execute": {"verify": {"verified": True}},
        }))
        client = Mock()
        result = run_typed_control_turn(
            "onayla", mode="approve", session_state=state, client=client, db_name="fixture.sqlite3",
            allow_approval_execute=True, approval_runner=executor,
        )
        self.assertTrue(result.success)
        self.assertEqual(executor.call_args.kwargs["action_id"], expected_id)
        self.assertIs(executor.call_args.kwargs["planner_client"], client)
        self.assertEqual(executor.call_args.kwargs["db_name"], "fixture.sqlite3")
        self.assertEqual(result.data["state"]["pending_actions"], [])
        self.assertEqual(result.data["direct_tool_calls"][0]["tool"], "execute_approved_operation")
        self.assertTrue(result.data["direct_tool_results"][0]["data"]["verify"]["verified"])

    def test_corrupt_proposal_cannot_reach_executor(self):
        state = self._state()
        state.pending_actions[0]["selected_record_count"] = 25
        executor = Mock(side_effect=AssertionError("Invalid proposal executed"))
        result = run_typed_control_turn(
            "onayla", mode="approve", session_state=state, client=None, db_name="fixture.sqlite3",
            allow_approval_execute=True, approval_runner=executor,
        )
        self.assertFalse(result.success)
        self.assertTrue(result.data["requires_reprepare"])
        executor.assert_not_called()

    def test_pause_before_approved_effect_does_not_claim_execution(self):
        from AI.processors.task_control import AgentTaskControl
        state = self._state()
        paused = AgentSessionState.from_dict(state.to_dict())
        paused.status = "paused"
        control = AgentTaskControl()
        control.request_pause()
        runner = Mock(return_value=Result.ok("Çalışma duraklatıldı.", data={"state": paused.to_dict()}))
        result = run_typed_control_turn("Onayla", mode="approve", session_state=state, client=None,
                                        db_name="unused", allow_approval_execute=True,
                                        approval_runner=runner, task_control=control)
        self.assertIs(runner.call_args.kwargs["task_control"], control)
        self.assertEqual(result.data["mode"], "paused")
        self.assertNotIn("direct_tool_calls", result.data)
        self.assertEqual(result.data["state"]["active_pending_action_id"], state.active_pending_action_id)
