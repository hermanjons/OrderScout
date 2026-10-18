from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from AI.processors import task_runtime, tools
from AI.processors.session_state import AgentSessionState, AgentTaskStep, GoalPlan, PendingActionSnapshot
from AI.processors.task_control import AgentTaskControl
from AI.processors.task_store import load_agent_task_state
from Feedback.processors.pipeline import Result


class TestAgenticTaskControl(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="orderscout-task-control-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.calls = []
        self.model_calls = []
        self.control = AgentTaskControl()
        self.pause_first = False
        self.first_failure = False
        self.registry = {
            name: tools.AgentTool(
                name=name, domain="stock", description="Observe a synthetic source",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                result_schema={"type": "object", "properties": {"count": {"type": "integer"}}},
                handler=lambda name=name: self._read(name),
            ) for name in ("stock.control.first", "stock.control.second")
        }

    def _read(self, name):
        self.calls.append(name)
        if name.endswith("first") and self.pause_first:
            self.control.request_pause()
        if name.endswith("first") and self.first_failure:
            return Result.fail("Temporary timeout", close_dialog=False, data={"retryable": True})
        return Result.ok("Source observed", data={"count": 4})

    def _state(self, *, second=True):
        first = AgentTaskStep(index=1, step_id="first", prompt="Read first source", operation_domain="stock",
                              operation_candidates=["stock.control.first"], expected_evidence=["count"])
        steps = [first]
        if second:
            steps.append(AgentTaskStep(index=2, step_id="second", prompt="Read second source", operation_domain="stock",
                                       operation_candidates=["stock.control.second"], depends_on=["first"], expected_evidence=["count"]))
        state = AgentSessionState(goal="Observe two sources", active_domain="stock")
        state.add_goal_plan(GoalPlan(goal=state.goal, domain="stock", steps=steps, source="llm_direct"))
        state.remaining_steps = list(steps)
        state.active_entities["execution_budget"] = {"contract_version": 1, "max_steps": len(steps),
                                                     "max_replans": 2, "started_steps": 0, "applied_replans": 0}
        return state

    @contextmanager
    def _catalog(self):
        with patch("AI.processors.tools.available_tools", return_value=self.registry), \
                patch.object(task_runtime, "_planner_operation_candidates", return_value=self.registry), \
                patch.object(task_runtime, "run_agent_turn", side_effect=AssertionError("Legacy routing")):
            yield

    def _planner(self, prompt):
        self.model_calls.append(prompt)
        if prompt.startswith("GoalPlan observation"):
            return json.dumps({"decision": "complete" if "Tamamlanan step: second\n" in prompt else "continue",
                               "reason": "Follow the observed source graph"})
        return json.dumps({"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
                           "unwanted_effect": False, "reason": "Read-only source"})

    def _run(self, state, *, planner=None, progress=None, persist=True):
        task_runtime._run_remaining_steps(state, planner_client=planner or self._planner, chat_client=None,
                                         db_name="synthetic-unused.db", task_control=self.control,
                                         persist=persist, task_store_root=str(self.root), progress_callback=progress)

    def test_pause_before_first_tool_preserves_graph_and_does_not_charge_budget(self):
        state = self._state()
        self.control.request_pause()
        with self._catalog():
            self._run(state)
        saved = load_agent_task_state(state.session_id, root=self.root)
        self.assertEqual(saved.status, "paused")
        self.assertEqual([step.step_id for step in saved.remaining_steps], ["first", "second"])
        self.assertEqual(saved.active_entities["execution_budget"]["started_steps"], 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.model_calls, [])
        self.assertFalse(saved.active_entities["goal_progress"]["complete"])
        self.assertIn("duraklattım", task_runtime._finalize_task_answer(saved))

    def test_pause_during_read_commits_observation_then_resume_runs_only_remaining_step(self):
        state = self._state()
        self.pause_first = True
        with self._catalog():
            self._run(state)
        saved = load_agent_task_state(state.session_id, root=self.root)
        observed = deepcopy(saved.completed_steps[0].to_dict())
        self.assertEqual(saved.active_entities["task_checkpoint"]["phase"], "step_observed")
        self.assertEqual(saved.active_entities["execution_budget"]["started_steps"], 1)
        self.assertEqual(self.model_calls, [])
        self.assertEqual(saved.completed_steps[0].result_data["tool_result"], {"count": 4})
        with self._catalog():
            resumed = task_runtime.resume_agent_task_by_id(state.session_id, planner_client=self._planner,
                                                            task_store_root=str(self.root))
        self.assertTrue(resumed.success, resumed.message)
        self.assertEqual(resumed.data["state"]["status"], "complete", resumed.data)
        self.assertEqual(self.calls, ["stock.control.first", "stock.control.second"])
        self.assertEqual(resumed.data["state"]["completed_steps"][0], observed)
        self.assertEqual(resumed.data["state"]["active_entities"]["execution_budget"]["started_steps"], 2)
        self.assertFalse(resumed.data["approval_granted"])

    def test_last_observation_pause_waits_for_completion_verdict_without_repeating_read(self):
        state = self._state(second=False)
        self.pause_first = True
        with self._catalog():
            self._run(state)
        self.assertEqual(state.status, "paused")
        self.assertEqual(state.remaining_steps, [])
        self.assertEqual(self.model_calls, [])
        with self._catalog():
            resumed = task_runtime.resume_read_task(state, planner_client=lambda prompt: json.dumps(
                {"decision": "complete", "reason": "The requested observation is complete"}),
                persist=True, task_store_root=str(self.root))
        self.assertTrue(resumed.success, resumed.message)
        self.assertEqual(resumed.data["state"]["status"], "complete", resumed.data)
        self.assertEqual(self.calls, ["stock.control.first"])
        self.assertEqual(resumed.data["state"]["active_entities"]["execution_budget"]["started_steps"], 1)

    def test_exact_revision_queue_survives_restart_and_blocks_old_graph_and_approval(self):
        state = self._state()
        messages = ["  Önce kapsamı değiştir.\nYalnız seçili dosya.  ", "Sonra raporu iki sayfada hazırla."]
        for message in messages:
            self.control.request_pause(reason="user_revision", user_message=message)
        with self._catalog():
            self._run(state)
            resumed = task_runtime.resume_agent_task_by_id(state.session_id, planner_client=self._planner,
                                                            task_store_root=str(self.root))
        saved = load_agent_task_state(state.session_id, root=self.root)
        self.assertEqual(saved.active_entities["task_control"], {
            "reason": "user_revision", "queued_user_messages": messages, "pause_requested": True})
        self.assertFalse(resumed.success)
        self.assertTrue(resumed.data["requires_user_revision_turn"])
        with patch.object(task_runtime, "execute_approved_operation", side_effect=AssertionError("Old approval")):
            approved = task_runtime.resume_agent_task_with_approval(saved.to_dict(), planner_client=self._planner)
        self.assertFalse(approved.success)
        self.assertTrue(approved.data["requires_user_revision_turn"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.model_calls, [])

    def test_ephemeral_headless_pause_requires_post_read_verdict_before_completion(self):
        state = self._state(second=False)
        self.pause_first = True
        with self._catalog():
            self._run(state, persist=False)
        self.assertEqual(state.active_entities["task_checkpoint"]["phase"], "step_observed")
        with self._catalog():
            resumed = task_runtime.resume_read_task(state, planner_client=lambda prompt: json.dumps(
                {"decision": "stop", "reason": "The requested goal is not yet satisfied"}), persist=False)
        self.assertTrue(resumed.success, resumed.message)
        self.assertEqual(resumed.data["state"]["status"], "failed", resumed.data)
        self.assertEqual(self.calls, ["stock.control.first"])
        self.assertFalse(resumed.data["approval_granted"])

    def test_pause_on_resume_preserves_unevaluated_observation_checkpoint(self):
        state = self._state()
        self.pause_first = True
        with self._catalog():
            self._run(state)
            resumed = task_runtime.resume_read_task(state, planner_client=self._planner, task_control=self.control,
                                                    persist=True, task_store_root=str(self.root))
        self.assertTrue(resumed.success)
        self.assertEqual(resumed.data["state"]["status"], "paused")
        self.assertEqual(resumed.data["state"]["active_entities"]["task_checkpoint"]["phase"], "step_observed")
        self.assertEqual(self.calls, ["stock.control.first"])
        self.assertEqual(self.model_calls, [])

    def test_pause_during_replan_preserves_new_graph_before_next_tool(self):
        state = self._state()
        def planner(prompt):
            self.model_calls.append(prompt)
            self.control.request_pause()
            return json.dumps({"decision": "replan", "reason": "Use the first observation", "steps": [{
                "id": "second", "operation_id": "stock.control.second", "depends_on": ["first"],
                "objective": "Read second source", "arguments": {}, "expected_evidence": ["count"],
            }]})
        with self._catalog():
            self._run(state, planner=planner)
        saved = load_agent_task_state(state.session_id, root=self.root)
        self.assertEqual(saved.status, "paused")
        self.assertEqual(saved.active_entities["task_checkpoint"]["phase"], "plan_evaluated")
        self.assertEqual(saved.active_goal_plan().step("second").status, "pending")
        self.assertEqual(saved.active_entities["execution_budget"]["applied_replans"], 1)
        with self._catalog():
            resumed = task_runtime.resume_agent_task_by_id(state.session_id, planner_client=self._planner,
                                                            task_store_root=str(self.root))
        self.assertEqual(resumed.data["state"]["status"], "complete", resumed.data)
        self.assertEqual(self.calls, ["stock.control.first", "stock.control.second"])

    def test_progress_pause_prevents_next_read_and_failed_read_pause_prevents_retry(self):
        state = self._state()
        def progress(_percent, message):
            if message.startswith("Adim 1/") and "tamamlandi" in message:
                self.control.request_pause()
        with self._catalog():
            self._run(state, progress=progress)
        self.assertEqual(state.status, "paused")
        self.assertEqual(self.calls, ["stock.control.first"])
        self.control = AgentTaskControl()
        self.pause_first = True
        self.first_failure = True
        state = self._state()
        with self._catalog():
            self._run(state)
        self.assertEqual(self.calls, ["stock.control.first", "stock.control.first"])
        self.assertEqual(state.completed_steps[0].status, "failed")
        self.assertEqual(state.completed_steps[0].attempt_count, 1)
        self.assertEqual(state.status, "paused")

    def test_pause_never_executes_or_changes_prepared_action_identity(self):
        state = self._state()
        action = state.add_pending_action(PendingActionSnapshot.refresh_identity({
            "action_type": "stock.action_create_manual_in_transaction", "status": "pending_approval",
            "approval_required": True, "execute_enabled": True, "arguments": {"payload": {"item_id": 12, "qty": 2}},
        }))
        state.status = "pending_approval"
        original = deepcopy(action)
        self.control.request_pause()
        with patch.object(task_runtime, "execute_approved_operation", side_effect=AssertionError("Paused effect")):
            result = task_runtime.resume_agent_task_with_approval(state.to_dict(), task_control=self.control,
                                                                  persist=True, task_store_root=str(self.root))
        self.assertTrue(result.success, result.message)
        self.assertFalse(result.data["approval_granted"])
        self.assertEqual(result.data["state"]["status"], "pending_approval")
        self.assertEqual(result.data["state"]["pending_actions"], [original])
        self.assertEqual(result.data["state"]["active_pending_action_id"], original["action_id"])

    def test_pause_during_approved_execution_keeps_effect_receipt_before_stopping_reads(self):
        state = self._state()
        action = state.add_pending_action(PendingActionSnapshot.refresh_identity({
            "action_type": "stock.action_create_manual_in_transaction", "status": "pending_approval",
            "approval_required": True, "execute_enabled": True, "arguments": {"payload": {"item_id": 12, "qty": 2}},
        }))
        state.status = "pending_approval"
        def execute(_action, **_options):
            self.control.request_pause()
            return Result.ok("Approved effect verified", data={"verify": {"verified": True, "verified_by": "synthetic_readback"}})
        with self._catalog(), patch("AI.processors.semantic_verifier.verify_pending_action_pre_execute", return_value=Result.ok("Allowed")), \
                patch.object(task_runtime, "execute_approved_operation", side_effect=execute) as executed:
            result = task_runtime.resume_agent_task_with_approval(state.to_dict(), task_control=self.control,
                                                                  persist=True, task_store_root=str(self.root))
        self.assertTrue(result.success, result.message)
        self.assertEqual(executed.call_count, 1)
        saved = load_agent_task_state(state.session_id, root=self.root)
        self.assertEqual(saved.status, "paused")
        self.assertEqual(saved.pending_actions, [])
        self.assertEqual(saved.observations[-1].facts["phase"], "execute_readback")
        self.assertTrue(saved.observations[-1].facts["verified"])
        effects = [event for event in saved.action_history if event["phase"] == "execute"]
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["action"]["action_id"], action["action_id"])
        self.assertEqual(self.calls, [])
        self.assertEqual(saved.active_entities["execution_budget"]["started_steps"], 0)

    def test_new_task_control_is_forwarded_and_old_revision_queue_does_not_carry(self):
        state = self._state()
        state.active_entities["task_control"] = {"reason": "user_revision", "queued_user_messages": ["Old guidance"], "pause_requested": True}
        self.control.request_pause()
        metadata = {"source": "llm_direct", "model_invoked": True, "step_ids": ["first"], "step_specs": [{
            "id": "first", "operation_id": "stock.control.first", "operation_domain": "stock", "objective": "Read source",
            "arguments": {}, "depends_on": [], "expected_evidence": ["count"],
        }]}
        with self._catalog(), patch.object(task_runtime, "_domain_task_plan", return_value=(["first"], metadata)):
            result = task_runtime.run_agent_task("New source goal", domain="general", planner_client=self._planner,
                                                 session_state=state, task_control=self.control, persist=True,
                                                 task_store_root=str(self.root))
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.data["state"]["status"], "paused", result.data)
        self.assertEqual(result.data["state"]["active_entities"]["task_control"]["queued_user_messages"], [])
        self.assertNotEqual(result.data["state"]["session_id"], state.session_id)
        self.assertEqual(self.calls, [])

