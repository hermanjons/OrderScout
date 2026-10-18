from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from AI.processors import report_builder, task_runtime, tools
from AI.processors.session_state import AgentSessionState, AgentTaskStep, GoalPlan
from AI.processors.task_store import load_agent_task_state, save_agent_task_state
from Feedback.processors.pipeline import Result


class ProcessLoss(BaseException):
    """Like process termination, bypass application Exception recovery."""


class TestAgenticCheckpointResume(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="orderscout-checkpoint-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.calls = []
        self.interrupt_second = False
        self.registry = {
            "stock.checkpoint.first": tools.AgentTool(
                name="stock.checkpoint.first", domain="stock", description="Read first synthetic source",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                result_schema={"type": "object", "properties": {"count": {"type": "integer"}}},
                handler=self._first,
            ),
            "stock.checkpoint.second": tools.AgentTool(
                name="stock.checkpoint.second", domain="stock", description="Read dependent synthetic source",
                parameters={"type": "object", "properties": {"prior": {"type": "integer"}},
                            "required": ["prior"], "additionalProperties": False},
                result_schema={"type": "object", "properties": {"count": {"type": "integer"}}},
                handler=self._second,
            ),
        }

    def _first(self):
        self.calls.append(("first", None))
        return Result.ok("First source observed", data={"count": 4})

    def _second(self, prior):
        self.calls.append(("second", prior))
        if self.interrupt_second:
            self.interrupt_second = False
            raise ProcessLoss()
        return Result.ok("Dependent source observed", data={"count": prior * 2})

    @contextmanager
    def _catalog(self, extra=None):
        registry = {**self.registry, **dict(extra or {})}
        with patch("AI.processors.tools.available_tools", return_value=registry), \
                patch.object(task_runtime, "_planner_operation_candidates", return_value=registry):
            yield registry

    def _state(self, maximum=2):
        first = AgentTaskStep(index=1, step_id="first", prompt="Read first source", objective="Read first source",
                              operation_candidates=["stock.checkpoint.first"], operation_domain="stock", expected_evidence=["count"])
        second = AgentTaskStep(index=2, step_id="second", prompt="Read dependent source", objective="Read dependent source",
                               operation_candidates=["stock.checkpoint.second"], operation_domain="stock", depends_on=["first"],
                               arguments={"prior": {"$from_step": "first", "path": "tool_result.count"}}, expected_evidence=["count"])
        state = AgentSessionState(goal="Research two authoritative sources", active_domain="stock")
        state.add_goal_plan(GoalPlan(goal=state.goal, domain="stock", steps=[first, second], source="llm_direct"))
        state.remaining_steps = [first, second]
        state.active_entities["execution_budget"] = {"contract_version": 1, "max_steps": maximum,
                                                     "max_replans": 2, "started_steps": 0, "applied_replans": 0}
        return state

    @staticmethod
    def _planner(prompt):
        if prompt.startswith("GoalPlan observation"):
            return json.dumps({"decision": "complete" if "Tamamlanan step: second\n" in prompt else "continue", "reason": "Use the persisted graph"})
        return json.dumps({"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
                           "unwanted_effect": False, "reason": "Read-only source observation"})

    def _run(self, state, planner=None, progress=None):
        task_runtime._run_remaining_steps(state, planner_client=planner or self._planner, chat_client=None,
                                         db_name="unused-synthetic.db", persist=True, task_store_root=str(self.root),
                                         progress_callback=progress)

    def test_process_loss_preserves_completed_receipt_and_recovers_only_inflight_read(self):
        state = self._state()
        self.interrupt_second = True
        with self._catalog(), self.assertRaises(ProcessLoss):
            self._run(state)
        restored = load_agent_task_state(state.session_id, root=self.root)
        self.assertEqual([step.step_id for step in restored.completed_steps], ["first"])
        self.assertEqual(restored.completed_steps[0].result_data["tool_result"]["count"], 4)
        self.assertEqual(restored.active_entities["task_checkpoint"]["inflight_step"]["step_id"], "second")
        self.assertEqual(restored.active_entities["execution_budget"]["started_steps"], 2)
        with self._catalog():
            resumed = task_runtime.resume_agent_task_by_id(state.session_id, planner_client=self._planner, task_store_root=str(self.root))
        self.assertTrue(resumed.success, resumed.message)
        self.assertEqual(resumed.data["state"]["status"], "complete", resumed.data)
        self.assertEqual(self.calls, [("first", None), ("second", 4), ("second", 4)])
        self.assertEqual(resumed.data["state"]["active_entities"]["execution_budget"]["started_steps"], 2)
        self.assertEqual(load_agent_task_state(state.session_id, root=self.root).status, "complete")

    def test_process_loss_after_progress_notification_keeps_exact_remaining_graph(self):
        state = self._state()
        def interrupt(percent, message):
            if message.startswith("Adim 1/") and "tamamlandi" in message:
                raise ProcessLoss()
        with self._catalog(), self.assertRaises(ProcessLoss):
            self._run(state, progress=interrupt)
        restored = load_agent_task_state(state.session_id, root=self.root)
        self.assertEqual([step.step_id for step in restored.remaining_steps], ["second"])
        self.assertEqual(restored.remaining_steps[0].depends_on, ["first"])
        with self._catalog():
            resumed = task_runtime.resume_read_task(restored, planner_client=self._planner, persist=True, task_store_root=str(self.root))
        self.assertTrue(resumed.success, resumed.message)
        self.assertEqual(resumed.data["state"]["status"], "complete", resumed.data)
        self.assertEqual(self.calls, [("first", None), ("second", 4)])

    def test_model_evaluation_interruption_never_repeats_observed_read(self):
        state = self._state()
        def lost_model(prompt):
            raise ProcessLoss()
        with self._catalog(), self.assertRaises(ProcessLoss):
            self._run(state, planner=lost_model)
        restored = load_agent_task_state(state.session_id, root=self.root)
        self.assertEqual(restored.active_entities["task_checkpoint"]["phase"], "step_observed")
        with self._catalog():
            resumed = task_runtime.resume_read_task(restored, planner_client=self._planner, persist=True, task_store_root=str(self.root))
        self.assertTrue(resumed.success, resumed.message)
        self.assertEqual(resumed.data["state"]["status"], "complete", resumed.data)
        self.assertEqual(self.calls, [("first", None), ("second", 4)])

    def test_replanned_frontier_and_charged_replan_budget_are_durable(self):
        state = self._state()
        def planner(prompt):
            if prompt.startswith("GoalPlan observation"):
                if "Tamamlanan step: first\n" in prompt:
                    return json.dumps({"decision": "replan", "reason": "Use the observed first source", "steps": [{
                        "id": "replacement", "operation_id": "stock.checkpoint.second", "depends_on": ["first"],
                        "arguments": {"prior": {"$from_step": "first", "path": "tool_result.count"}},
                        "objective": "Read dependent source from the current observation", "expected_evidence": ["count"],
                    }]})
                return json.dumps({"decision": "complete", "reason": "Both authoritative sources observed"})
            return self._planner(prompt)
        def lost_progress(_percent, message):
            if message.startswith("Adim 1/") and "tamamlandi" in message:
                raise ProcessLoss()
        with self._catalog(), self.assertRaises(ProcessLoss):
            self._run(state, planner=planner, progress=lost_progress)
        restored = load_agent_task_state(state.session_id, root=self.root)
        self.assertEqual([step.step_id for step in restored.remaining_steps], ["replacement"], restored.to_dict())
        self.assertEqual(restored.active_entities["execution_budget"]["applied_replans"], 1)
        with self._catalog():
            resumed = task_runtime.resume_agent_task_by_id(state.session_id, planner_client=planner,
                                                           task_store_root=str(self.root))
        self.assertTrue(resumed.success, resumed.message)
        self.assertEqual(resumed.data["state"]["status"], "complete", resumed.data)
        self.assertEqual(self.calls, [("first", None), ("second", 4)])
        self.assertEqual(resumed.data["state"]["active_entities"]["execution_budget"]["started_steps"], 2)
        self.assertEqual(resumed.data["state"]["active_entities"]["execution_budget"]["applied_replans"], 1)

    def _report_state(self):
        snapshot = report_builder.build_observation_report_snapshot(
            title="Checkpoint export", sources=[{
                "source_id": "source", "source_step_id": "authoritative-read", "operation_id": "stock.checkpoint.first",
                "result": {"count": 4},
            }], sheets=[{"name": "Source", "source_id": "source", "rows_path": "", "columns": [
                {"key": "count", "label": "Count", "source_path": "count", "data_type": "integer"},
            ]}],
        )
        output = self.root / "approved-report.xlsx"
        built = AgentTaskStep(
            index=1, step_id="built", prompt="Build report from observed source", objective="Build report from observed source",
            operation_candidates=["reports.build_snapshot"], operation_domain="reports", status="completed",
            verification_status="observed", tool_names=["reports.build_snapshot"],
            result_data={"tool_result": {"tool": "reports.build_snapshot", "report_snapshot": snapshot.to_dict(),
                                          "report_content_hash": snapshot.content_hash}},
        )
        prepare = AgentTaskStep(
            index=2, step_id="prepare", prompt="Prepare my local report", objective="Prepare my local report",
            operation_candidates=["reports.xlsx.prepare"], operation_domain="reports",
            depends_on=["built"],
            arguments={"report_snapshot": {"$from_step": "built", "path": "tool_result.report_snapshot"},
                       "output_path": str(output)},
            expected_evidence=["action", "snapshot_id", "output_path"],
        )
        followup = AgentTaskStep(
            index=3, step_id="second", prompt="Read the source after export", objective="Read the source after export",
            operation_candidates=["stock.checkpoint.second"], operation_domain="stock", depends_on=["prepare"],
            arguments={"prior": 4}, expected_evidence=["count"],
        )
        state = AgentSessionState(goal="Create my local report then read a source", active_domain="general")
        state.add_goal_plan(GoalPlan(goal=state.goal, domain="general", source="llm_direct", steps=[built, prepare, followup]))
        state.active_entities["turn_interpretation"] = {"mode": "act", "valid": True, "domain": "general",
                                                        "objective": state.goal, "intent_kind": "action"}
        state.remaining_steps = [prepare, followup]
        state.completed_steps = [built]
        state.active_entities["execution_budget"] = {"contract_version": 1, "max_steps": 3,
                                                     "max_replans": 2, "started_steps": 1, "applied_replans": 0}
        return state, output, tools.available_tools()["reports.xlsx.prepare"]

    def test_pending_authority_is_persisted_before_user_progress_and_never_auto_approved(self):
        state, output, prepare_tool = self._report_state()
        def lost_progress(_percent, message):
            if message.startswith("Adim 2/") and "tamamlandi" in message:
                raise ProcessLoss()
        with self._catalog({prepare_tool.name: prepare_tool}), self.assertRaises(ProcessLoss):
            self._run(state, progress=lost_progress)
        restored = load_agent_task_state(state.session_id, root=self.root)
        self.assertEqual(restored.status, "pending_approval")
        pending = restored.active_pending_action()
        self.assertIsNotNone(pending)
        self.assertEqual(pending["arguments"]["output_path"], str(output))
        self.assertFalse(output.exists())
        with self._catalog({prepare_tool.name: prepare_tool}):
            resumed = task_runtime.resume_read_task(restored, planner_client=self._planner)
        self.assertFalse(resumed.success)
        self.assertTrue(resumed.data["approval_required"])
        self.assertEqual(resumed.data["state"]["active_pending_action_id"], restored.active_pending_action_id)
        self.assertFalse(output.exists())
        self.assertEqual(self.calls, [])

    def test_approved_export_receipt_survives_process_loss_and_export_is_not_replayed(self):
        from AI.views import actions
        from openpyxl import load_workbook
        state, output, prepare_tool = self._report_state()
        with self._catalog({prepare_tool.name: prepare_tool}):
            self._run(state)
        self.assertEqual(state.status, "pending_approval", state.to_dict())
        original_export = actions.action_export_report_snapshot_xlsx
        exports = []
        def recorded_export(*args, **kwargs):
            exports.append(str(kwargs.get("output_path")))
            return original_export(*args, **kwargs)
        self.interrupt_second = True
        with self._catalog({prepare_tool.name: prepare_tool}), \
                patch.object(actions, "action_export_report_snapshot_xlsx", side_effect=recorded_export), \
                self.assertRaises(ProcessLoss):
            task_runtime.resume_agent_task_with_approval(
                state.to_dict(), action_id=state.active_pending_action_id, approved_by="isolated-user",
                planner_client=self._planner, persist=True, task_store_root=str(self.root),
                audit_path=str(self.root / "audit.jsonl"),
            )
        restored = load_agent_task_state(state.session_id, root=self.root)
        self.assertEqual(restored.pending_actions, [])
        self.assertEqual(restored.active_pending_action_id, "")
        self.assertEqual(restored.completed_steps[-1].verification_status, "verified")
        self.assertEqual(restored.action_history[-1]["verify"]["verified_by"], "xlsx_exact_snapshot_readback")
        saved_file_hash = hashlib.sha256(output.read_bytes()).hexdigest()
        with self._catalog({prepare_tool.name: prepare_tool}), \
                patch.object(actions, "action_export_report_snapshot_xlsx", side_effect=recorded_export):
            resumed = task_runtime.resume_agent_task_by_id(state.session_id, planner_client=self._planner,
                                                           task_store_root=str(self.root))
        self.assertTrue(resumed.success, resumed.message)
        self.assertEqual(resumed.data["state"]["status"], "complete", resumed.data)
        self.assertEqual(len(exports), 1)
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), saved_file_hash)
        workbook = load_workbook(output, read_only=True, data_only=True)
        try:
            self.assertEqual(tuple(workbook["Source"].values)[1], (4,))
        finally:
            workbook.close()
        self.assertEqual(self.calls, [("second", 4), ("second", 4)])

    def test_public_start_persists_boundary_before_restart(self):
        state = self._state()
        plan = {"steps": [{
            "id": step.step_id, "operation_id": step.operation_candidates[0], "arguments": step.arguments,
            "depends_on": step.depends_on, "objective": step.objective, "expected_evidence": step.expected_evidence,
        } for step in state.remaining_steps]}
        def planner(prompt):
            if prompt.startswith(("GoalPlan observation", "OrderScout semantic action verifier")):
                return self._planner(prompt)
            return json.dumps(plan)
        def lost_progress(_percent, message):
            if message.startswith("Adim 1/") and "tamamlandi" in message:
                raise ProcessLoss()
        with self._catalog(), self.assertRaises(ProcessLoss):
            task_runtime.run_agent_task(
                "Read two stock sources", domain="stock", session_state=state.to_dict(), planner_client=planner,
                max_steps=2, persist=True, task_store_root=str(self.root), progress_callback=lost_progress,
                turn_interpretation={"mode": "act", "intent_kind": "action", "domain": "stock", "valid": True,
                                     "objective": "Read two stock sources", "requires_clarification": False},
            )
        saved = list(self.root.glob("*.json"))
        self.assertEqual(len(saved), 1)
        restored = AgentSessionState.from_dict(json.loads(saved[0].read_text(encoding="utf-8")))
        self.assertEqual([step.step_id for step in restored.completed_steps], ["first"])
        self.assertEqual([step.step_id for step in restored.remaining_steps], ["second"])
        with self._catalog():
            resumed = task_runtime.resume_agent_task_by_id(restored.session_id, planner_client=planner,
                                                           task_store_root=str(self.root))
        self.assertTrue(resumed.success, resumed.message)
        self.assertEqual(resumed.data["state"]["status"], "complete", resumed.data)
        self.assertEqual(self.calls, [("first", None), ("second", 4)])

    def test_read_resume_cannot_grant_pending_approval_or_run_effectful_graph(self):
        state = self._state()
        state.pending_actions = [{"action_id": "pending-immutable", "action_type": "synthetic.write"}]
        state.active_pending_action_id = "pending-immutable"
        before = state.to_dict()
        with self._catalog():
            result = task_runtime.resume_read_task(state, planner_client=self._planner)
        self.assertFalse(result.success)
        self.assertTrue(result.data["approval_required"])
        self.assertEqual(result.data["state"]["active_pending_action_id"], before["active_pending_action_id"])
        self.assertEqual(self.calls, [])
        state.pending_actions = []
        state.active_pending_action_id = ""
        effectful = replace(self.registry["stock.checkpoint.second"], requires_approval=True, action_type="prepare")
        with self._catalog({effectful.name: effectful}):
            result = task_runtime.resume_read_task(state, planner_client=self._planner)
        self.assertFalse(result.success)
        self.assertEqual(result.data["read_resume_operation_rejected"], "second")
        self.assertEqual(self.calls, [])

    def test_exhausted_budget_and_terminal_state_cannot_be_reset_by_resume(self):
        state = self._state(maximum=1)
        state.active_entities["execution_budget"]["started_steps"] = 1
        with self._catalog():
            result = task_runtime.resume_read_task(state, planner_client=self._planner)
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.data["state"]["status"], "failed")
        self.assertEqual(result.data["state"]["active_entities"]["goal_progress"]["reason"], "execution_budget_exhausted")
        self.assertEqual(self.calls, [])
        for status in ("complete", "cancelled", "superseded", "failed"):
            state.status = status
            with self._catalog():
                result = task_runtime.resume_read_task(state, planner_client=self._planner)
            self.assertFalse(result.success, status)

    def test_saved_model_identity_and_authority_survive_serialization(self):
        state = self._state()
        state.active_entities["runtime_context"] = {"source": "cloud", "provider_id": 1, "model_name": "exact/model"}
        save_agent_task_state(state, root=self.root)
        restored = load_agent_task_state(state.session_id, root=self.root)
        with self._catalog():
            missing = task_runtime.resume_read_task(restored)
            mismatched = task_runtime.resume_read_task(restored, planner_client=self._planner,
                                                       runtime_context={"source": "cloud", "provider_id": 1, "model_name": "other/model"})
        self.assertFalse(missing.success)
        self.assertTrue(missing.data["resume_client_required"])
        self.assertFalse(mismatched.success)
        self.assertTrue(mismatched.data["resume_model_mismatch"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
