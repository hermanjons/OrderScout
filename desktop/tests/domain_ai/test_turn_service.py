from __future__ import annotations

import copy
import unittest
from unittest.mock import Mock

from AI.processors.session_state import AgentSessionState, AgentTaskStep, GoalPlan
from AI.processors.task_runtime import (
    model_authored_projection_acceptance,
    record_conversation_exchange,
)
from AI.processors.turn_service import run_interpreted_turn
from Feedback.processors.pipeline import Result


class TestTurnService(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock(name="provider", side_effect=AssertionError("Unexpected model call"))
        self.history = [{"role": "user", "content": "Previous user message"}]
        self.task_runner = Mock(name="task_runner")
        self.observation_reader = Mock(name="observation_reader")
        self.conversation_runner = Mock(name="conversation_runner")
        self.capability_reader = Mock(name="capability_reader")
        self.policy_context_builder = Mock(name="policy_context_builder", return_value={})

    def _run(self, interpretation: dict, *, success: bool = True, **options) -> Result | None:
        message = options.pop("message", "Current user message")
        return run_interpreted_turn(
            message,
            interpretation_result=Result(success=success, data=interpretation),
            client=self.client,
            history=self.history,
            db_name="ignored.sqlite3",
            task_runner=self.task_runner,
            observation_reader=self.observation_reader,
            conversation_runner=self.conversation_runner,
            capability_reader=self.capability_reader,
            policy_context_builder=self.policy_context_builder,
            **options,
        )

    def _assert_no_operations(self) -> None:
        for callback in (
            self.client,
            self.task_runner,
            self.observation_reader,
            self.conversation_runner,
            self.capability_reader,
            self.policy_context_builder,
        ):
            callback.assert_not_called()

    def test_provider_outage_preserves_pending_state_without_reusing_old_verification(self) -> None:
        state = AgentSessionState(
            goal="Prepare labels",
            active_domain="orders",
            status="pending_approval",
            pending_actions=[{"action_id": "approved-exact-set"}],
            active_pending_action_id="approved-exact-set",
        )
        state.active_entities["response_synthesis"] = {
            "final_source": "verified_model_candidate",
            "candidate_accepted": True,
        }
        original = copy.deepcopy(state.to_dict())
        history_before = copy.deepcopy(self.history)

        result = self._run(
            {
                "valid": False,
                "provider_unavailable": True,
                "mode": "provider_unavailable",
                "answer": "Model kota sınırına ulaştı.",
                "provider_failure": {"reason": "quota_exhausted"},
                "decision_path": "typed_model_turn_provider_unavailable",
            },
            session_state=state,
        )

        self.assertIsInstance(result, Result)
        self.assertTrue(result.success)
        self.assertEqual(result.data["mode"], "provider_unavailable")
        self.assertEqual(result.message, "Model kota sınırına ulaştı.")
        self.assertFalse(result.data["model_invoked"])
        self.assertTrue(result.data["model_invocation_attempted"])
        after = result.data["session_state"]
        self.assertEqual(after["pending_actions"], original["pending_actions"])
        self.assertEqual(after["active_pending_action_id"], "approved-exact-set")
        self.assertEqual(after["status"], "pending_approval")
        self.assertEqual(after["active_domain"], "orders")
        synthesis = after["active_entities"]["response_synthesis"]
        self.assertEqual(synthesis["final_source"], "typed_provider_unavailable")
        self.assertFalse(synthesis["candidate_accepted"])
        self.assertEqual(state.to_dict(), original)
        self.assertEqual(self.history, history_before)
        self._assert_no_operations()

    def test_invalid_interpretation_cannot_route_to_a_task_even_in_success_wrapper(self) -> None:
        for success in (True, False):
            with self.subTest(success=success):
                state = AgentSessionState(
                    goal="Read orders",
                    active_domain="orders",
                    status="complete",
                ).to_dict()
                original = copy.deepcopy(state)
                result = self._run(
                    {"valid": False, "mode": "act", "domain": "stock"},
                    success=success,
                    session_state=state,
                )
                self.assertEqual(result.data["mode"], "clarification")
                self.assertEqual(
                    result.data["decision_path"],
                    "typed_model_turn_interpretation_failed_closed",
                )
                self.assertIn("orders", result.message)
                self.assertIn("netleştir", result.message)
                self.assertEqual(result.data["tool_names"], [])
                self.assertEqual(result.data["session_state"]["active_domain"], "orders")
                self.assertEqual(state, original)
        self._assert_no_operations()

    def test_clarification_uses_typed_missing_input_and_retains_contract_receipt(self) -> None:
        receipt = {"accepted": {"missing_input": "target"}}
        result = self._run(
            {
                "valid": True,
                "mode": "act",
                "domain": "orders",
                "requires_clarification": True,
                "missing_input": "target",
                "clarification": "Kayıtların tamamı eksik ve mağazanız bağlı değil.",
                "turn_contract_provenance": receipt,
            }
        )

        self.assertEqual(result.message, "Hangi kayıt veya kayıtlar üzerinde işlem yapmamı istiyorsun?")
        self.assertEqual(result.data["decision_path"], "typed_model_clarification")
        state = result.data["session_state"]
        user_turn = next(row for row in state["conversation_turns"] if row["role"] == "user")
        self.assertEqual(user_turn["semantic_contract"]["missing_input"], "target")
        self.assertEqual(user_turn["semantic_contract"]["turn_contract_provenance"], receipt)
        self.assertEqual(state["active_entities"]["response_synthesis"]["final_source"], "typed_clarification")
        self._assert_no_operations()

    def test_existing_observation_correction_never_starts_new_business_operations(self) -> None:
        expected = Result.ok("Corrected existing observation")
        self.observation_reader.return_value = expected
        state = AgentSessionState(goal="Previous task", active_domain="orders")
        interpretation = {
            "valid": True,
            "mode": "correct",
            "domain": "orders",
            "intent_kind": "correction",
            "operation_policy": "existing_observations_only",
            "semantic_contract": {"requested_fields": ["count"]},
        }

        result = self._run(interpretation, session_state=state)

        self.assertIs(result, expected)
        self.observation_reader.assert_called_once_with(
            "Current user message", interpretation=interpretation, session_state=state
        )
        self.task_runner.assert_not_called()
        self.conversation_runner.assert_not_called()
        self.policy_context_builder.assert_not_called()
        self.client.assert_not_called()

    def test_capability_overview_records_catalog_evidence_without_a_task_or_model_reply(self) -> None:
        catalog = {"domain": "orders", "operation_ids": ["orders.summary"]}
        self.capability_reader.return_value = ("Sipariş özeti çıkarabilirim.", catalog)
        result = self._run(
            {"valid": True, "mode": "explain", "domain": "orders", "intent_kind": "capability_overview"}
        )

        self.assertEqual(result.data["answer"], "Sipariş özeti çıkarabilirim.")
        self.assertEqual(result.data["decision_path"], "typed_capability_catalog_grounded")
        self.assertEqual(result.data["direct_tool_results"][0]["data"], catalog)
        self.assertEqual(result.data["direct_tool_calls"][0]["arguments"], {"domain": "orders"})
        self.capability_reader.assert_called_once_with("orders")
        self.task_runner.assert_not_called()
        self.conversation_runner.assert_not_called()
        self.client.assert_not_called()

    def test_policy_explanation_passes_canonical_facts_and_operation_policy_to_conversation(self) -> None:
        policy = {"source": "canonical_runtime_policy", "assertions": [{"fact": "Approval required"}]}
        self.policy_context_builder.return_value = policy
        expected = Result.ok("Policy explanation")
        self.conversation_runner.return_value = expected
        interpretation = {
            "valid": True,
            "mode": "explain",
            "domain": "orders",
            "intent_kind": "policy_explanation",
            "objective": "Explain approval",
            "operation_policy": "existing_observations_only",
        }
        result = self._run(interpretation)

        self.assertIs(result, expected)
        self.policy_context_builder.assert_called_once_with(interpretation)
        self.conversation_runner.assert_called_once_with(
            "Current user message",
            mode="explain",
            objective="Explain approval",
            chat_client=self.client,
            history=self.history,
            session_state=None,
            operation_policy="existing_observations_only",
            policy_context=policy,
        )
        self.observation_reader.assert_not_called()
        self.capability_reader.assert_not_called()
        self.task_runner.assert_not_called()

    def test_capability_turn_replaces_previous_business_final_receipt_and_preserves_task_history(self) -> None:
        catalog_answer = "Sipariş özeti çıkarabilir ve etiket hazırlayabilirim."
        catalog = {"domain": "orders", "operation_ids": ["orders.summary"]}
        self.capability_reader.return_value = (catalog_answer, catalog)

        for previously_allowed in (True, False):
            with self.subTest(previously_allowed=previously_allowed):
                def complete_business_turn(message, **options):
                    step = AgentTaskStep(
                        index=1, step_id="prior_summary", prompt=message,
                        status="completed", tool_names=["orders.summary"],
                    )
                    state = AgentSessionState(
                        goal=message, active_domain="orders", status="complete",
                        completed_steps=[step],
                        goal_plans=[GoalPlan(
                            goal=message, domain="orders", steps=[step], status="completed",
                        )],
                        active_selection_ids={"orders": "previous-exact-selection"},
                    )
                    state = record_conversation_exchange(
                        session_state=state, user_message=message,
                        assistant_message="Önceki sipariş özeti.", mode="inspect",
                        objective=message, active_domain="orders",
                    )
                    state.active_entities.update({
                        "final_answer": "Önceki sipariş özeti.",
                        "response_synthesis": {
                            "final_source": "verified_model_candidate",
                            "candidate_accepted": True,
                            "final_projection_verified": True,
                        },
                        "response_verifications": [{
                            "source": "final_response", "allowed": previously_allowed,
                            "reason_codes": [] if previously_allowed else ["previous_rejection"],
                        }],
                        "task_plan": {
                            "source": "llm_direct", "planner_invoked": True,
                            "llm_step_ids": ["prior_summary"],
                            "step_specs": [{"id": "prior_summary", "operation_id": "orders.summary"}],
                            "deterministic_business_steps_inserted": False,
                        },
                    })
                    return Result.ok("Önceki sipariş özeti.", data={"session_state": state.to_dict()})

                self.task_runner.side_effect = complete_business_turn
                first = self._run(
                    {"valid": True, "mode": "inspect", "domain": "orders"},
                    message="Siparişlerimi özetle",
                )
                original = copy.deepcopy(first.data["session_state"])
                second = self._run(
                    {
                        "valid": True, "mode": "explain", "domain": "orders",
                        "intent_kind": "capability_overview",
                    },
                    message="Sipariş tarafında neler yapabilirsin?",
                    session_state=first.data["session_state"],
                )
                current = second.data["session_state"]

                self.assertEqual(current["active_entities"]["final_answer"], catalog_answer)
                synthesis = current["active_entities"]["response_synthesis"]
                self.assertEqual(synthesis["final_source"], "typed_capability_catalog")
                self.assertFalse(synthesis["candidate_received"])
                self.assertFalse(synthesis["candidate_accepted"])
                receipts = current["active_entities"]["response_verifications"]
                self.assertEqual(len(receipts), 1)
                self.assertTrue(receipts[0]["allowed"])
                self.assertEqual(receipts[0]["source"], "final_response")
                self.assertEqual(receipts[0]["verification_kind"], "canonical_capability_catalog")
                self.assertEqual(receipts[0]["reason_codes"], [])
                self.assertEqual(receipts[0]["operation_ids"], ["orders.summary"])
                self.assertFalse(model_authored_projection_acceptance(
                    current, final_model_response_received=True,
                )["verified_business_projection"])
                for key in ("goal_plans", "completed_steps", "active_selection_ids"):
                    self.assertEqual(current[key], original[key])
                self.assertEqual(
                    [row["role"] for row in current["conversation_turns"]],
                    ["user", "assistant", "user", "assistant"],
                )
                self.assertEqual(first.data["session_state"], original)

    def test_task_dispatch_keeps_typed_domain_and_adapter_persistence_budget(self) -> None:
        state = AgentSessionState(goal="Previous Orders task", active_domain="orders")
        progress = Mock()
        context = {"source": "cloud", "provider_code": "test"}
        expected = Result.ok("Task result")
        self.task_runner.return_value = expected
        for mode, domain in (("inspect", "stock"), ("act", "orders"), ("correct", "finance")):
            with self.subTest(mode=mode, domain=domain):
                self.task_runner.reset_mock()
                interpretation = {"valid": True, "mode": mode, "domain": domain}
                result = self._run(
                    interpretation,
                    session_state=state,
                    persist=True,
                    max_steps=10,
                    runtime_context=context,
                    progress_callback=progress,
                )
                self.assertIs(result, expected)
                options = self.task_runner.call_args.kwargs
                self.assertEqual(options["domain"], domain)
                self.assertIs(options["planner_client"], self.client)
                self.assertIs(options["chat_client"], self.client)
                self.assertIs(options["session_state"], state)
                self.assertIs(options["history"], self.history)
                self.assertIs(options["progress_callback"], progress)
                self.assertEqual(options["runtime_context"], context)
                self.assertEqual(options["turn_interpretation"], interpretation)
                self.assertTrue(options["persist"])
                self.assertEqual(options["max_steps"], 10)
        self.conversation_runner.assert_not_called()
        self.observation_reader.assert_not_called()
        self.client.assert_not_called()

    def test_task_dispatch_keeps_domain_runner_default_budget_when_adapter_omits_it(self) -> None:
        self._run({"valid": True, "mode": "inspect", "domain": "orders"})

        options = self.task_runner.call_args.kwargs
        self.assertNotIn("max_steps", options)
        self.assertFalse(options["persist"])

    def test_unsupported_domain_and_mode_fail_closed_instead_of_returning_legacy_fallback(self) -> None:
        for interpretation in (
            {"valid": True, "mode": "act", "domain": "unknown"},
            {"valid": True, "mode": "unexpected", "domain": "orders"},
        ):
            with self.subTest(interpretation=interpretation):
                result = self._run(interpretation)
                self.assertIsInstance(result, Result)
                self.assertEqual(result.data["mode"], "clarification")
                self.assertEqual(result.data["decision_path"], "typed_turn_unhandled_fail_closed")
        self._assert_no_operations()

    def test_registered_general_task_is_dispatched_to_shared_runtime(self) -> None:
        expected = Result.ok("General work started")
        self.task_runner.return_value = expected
        result = self._run({"valid": True, "mode": "inspect", "domain": "general", "objective": "Research across modules"})
        self.assertIs(result, expected)
        self.assertEqual(self.task_runner.call_args.kwargs["domain"], "general")
        self.assertEqual(self.task_runner.call_args.kwargs["max_steps"], 24)
        self.conversation_runner.assert_not_called()

    def test_approval_and_cancellation_are_left_to_the_adapter_without_dispatch(self) -> None:
        for mode in ("approve", "cancel"):
            with self.subTest(mode=mode):
                self.assertIsNone(self._run({"valid": True, "mode": mode, "domain": "general"}))
        self._assert_no_operations()


if __name__ == "__main__":
    unittest.main()
