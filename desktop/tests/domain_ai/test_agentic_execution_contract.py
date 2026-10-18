from __future__ import annotations

import json
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from AI.processors import task_runtime
from AI.processors.session_state import AgentSessionState, AgentTaskStep, GoalPlan, Observation
from AI.processors.tools import AgentTool
from Feedback.processors.pipeline import Result


class TestAgenticExecutionContract(unittest.TestCase):
    def setUp(self):
        self.registry = {
            name: AgentTool(
                name=name, domain="stock", description="Read authoritative evidence",
                parameters={"type": "object", "properties": {}},
                result_schema={"type": "object", "properties": {"count": {"type": "integer"}}},
                handler=Mock(side_effect=AssertionError("Unbound operation execution")),
            )
            for name in ("stock.first", "stock.second", "stock.third", "stock.fourth")
        }

    def _state(self, *, maximum=4):
        step = AgentTaskStep(
            index=1, step_id="initial", prompt="Read first source", objective="Read first source",
            operation_candidates=["stock.first"], operation_domain="stock",
            expected_evidence=["count"],
        )
        state = AgentSessionState(goal="Research and finish the requested work", active_domain="stock", status="running")
        state.add_goal_plan(GoalPlan(
            goal=state.goal, domain="stock", steps=[step], source="llm_direct",
        ))
        state.remaining_steps = [step]
        state.active_entities["execution_budget"] = {
            "contract_version": 1, "max_steps": maximum, "max_replans": maximum,
            "started_steps": 0, "applied_replans": 0,
        }
        return state

    def _run(self, state, decisions, *, results=None):
        replies = iter(decisions)
        def planner(prompt):
            planner.calls.append(prompt)
            return json.dumps(next(replies))
        planner.calls = []
        calls = []

        def read(_state, step, **_options):
            calls.append(step.step_id)
            payload = (results or {}).get(step.step_id, {"count": 0})
            return Result.ok("Authoritative read", data={
                "mode": "tool", "tool_call": {"tool": step.operation_candidates[0]},
                "tool_result": payload,
            })

        with patch("AI.processors.tools.available_tools", return_value=self.registry), \
                patch.object(task_runtime, "_planner_operation_candidates", return_value=self.registry), \
                patch.object(task_runtime, "_run_bound_domain_read_step", side_effect=read), \
                patch.object(task_runtime, "run_agent_turn", side_effect=AssertionError("Legacy rerouting")):
            task_runtime._run_remaining_steps(
                state, planner_client=planner, chat_client=None, db_name="unused.sqlite3",
            )
        return calls, planner

    @staticmethod
    def _replacement(*steps):
        return {"decision": "replan", "reason": "Observation requires additional work", "steps": [
            {"id": identity, "operation_id": operation, "objective": "Read next evidence",
             "arguments": {}, "depends_on": dependencies, "expected_evidence": ["count"]}
            for identity, operation, dependencies in steps
        ]}

    def test_single_discovery_step_can_grow_into_two_dependent_steps(self):
        state = self._state(maximum=3)
        calls, planner = self._run(state, [
            self._replacement(("second", "stock.second", ["initial"]), ("third", "stock.third", ["second"])),
            {"decision": "continue", "reason": "One planned step remains"},
            {"decision": "complete", "reason": "Required work is finished"},
        ])
        self.assertEqual(calls, ["initial", "second", "third"])
        self.assertEqual(state.status, "complete")
        self.assertEqual(state.active_entities["execution_budget"]["started_steps"], 3)
        self.assertEqual(len(planner.calls), 3)

    def test_replan_can_reuse_unexecuted_node_ids_without_rebinding_completed_evidence(self):
        state = self._state(maximum=3)
        pending = [AgentTaskStep(index=index, step_id=identity, prompt="Pending read", operation_candidates=[operation], operation_domain="stock")
                   for index, identity, operation in ((2, "second", "stock.second"), (3, "third", "stock.third"))]
        pending[0].depends_on = ["initial"]
        pending[0].expected_evidence = ["count"]
        pending[1].depends_on = ["second"]
        pending[1].expected_evidence = ["count"]
        state.remaining_steps.extend(pending)
        state.active_goal_plan().steps.extend(pending)
        calls, _ = self._run(state, [
            self._replacement(("second", "stock.second", ["initial"]), ("third", "stock.third", ["second"])),
            {"decision": "continue", "reason": "Third node remains"},
            {"decision": "complete", "reason": "All reads complete"},
        ])
        self.assertEqual(calls, ["initial", "second", "third"])
        self.assertTrue(state.active_entities["goal_evaluations"][0]["applied"])
        self.assertEqual(state.status, "complete")

    def test_general_source_period_is_preserved_and_joined_machine_fields_are_split(self):
        from AI.processors.tools import available_tools
        tool = available_tools()["orders.summary"]
        diagnostics = []
        spec = {"id": "source", "operation_id": tool.name, "arguments": {"period": "last_14_days"},
                "depends_on": [], "expected_evidence": ["total_orders, estimated_revenue"]}
        accepted, rejected = task_runtime._validate_direct_plan_specs(
            "general", [spec], "Research periods", allowed_operations={tool.name: tool}, max_steps=1,
            authorization_context={"mode": "inspect", "intent_kind": "data_read", "semantic_contract": {"period": "last_7_days"}},
            validation_diagnostics=diagnostics,
        )
        self.assertEqual(rejected, [], diagnostics)
        self.assertEqual(accepted[0]["arguments"]["period"], "last_14_days")
        self.assertEqual(accepted[0]["expected_evidence"], ["total_orders", "estimated_revenue"])
        state = AgentSessionState(goal="Research periods", active_domain="general")
        state.active_entities["turn_interpretation"] = {"semantic_contract": {"period": "last_7_days"}}
        step = AgentTaskStep(index=1, step_id="source", prompt=state.goal, operation_candidates=[tool.name],
                             arguments={"period": "last_14_days"})
        arguments, problems, bindings = task_runtime._resolve_step_arguments(state, step, tool)
        self.assertEqual(problems, [])
        self.assertEqual(arguments["period"], "last_14_days")
        self.assertNotEqual(bindings.get("period"), "typed_semantic_contract.period")
        state.active_domain = "orders"
        arguments, problems, bindings = task_runtime._resolve_step_arguments(state, step, tool)
        self.assertEqual(arguments["period"], "last_7_days")
        self.assertEqual(bindings["period"], "typed_semantic_contract.period")
        spec["expected_evidence"] = ["Read the total orders and revenue"]
        accepted, rejected = task_runtime._validate_direct_plan_specs(
            "general", [spec], "Research periods", allowed_operations={tool.name: tool}, max_steps=1,
            validation_diagnostics=diagnostics,
        )
        self.assertEqual(accepted, [])
        self.assertEqual(rejected, ["source"])
        self.assertIn("expected_evidence:exact_machine_fields_required", diagnostics[-1]["reason_codes"])

    def test_continuation_keeps_initial_calculation_schema_and_current_observation_scope(self):
        from AI.processors.tools import available_tools
        registry = available_tools()
        state = AgentSessionState(goal="Compare observed business periods", active_domain="general")
        state.active_entities["task_plan"] = {"operation_candidate_ids": ["analysis.calculate"]}
        candidates = task_runtime._continuation_operation_candidates(state, {"orders.summary": registry["orders.summary"]})
        self.assertIn("analysis.calculate", candidates)
        step = AgentTaskStep(index=1, step_id="observed", prompt=state.goal, tool_names=["orders.summary"], status="completed",
            verification_status="observed", result_data={"tool_result": {"period": "2026-10-02..2026-10-08", "start_ms": 100, "end_ms": 200, "currency": "TRY"}})
        state.completed_steps = [step]
        observation = Observation.create(domain="orders", operation_name="orders.summary", success=True)
        prompt = task_runtime._goal_evaluation_prompt(state, step, observation, operation_candidates=candidates, max_steps=2)
        self.assertIn('"start_ms": 100', prompt)
        self.assertIn('"end_ms": 200', prompt)
        self.assertIn('"currency": "TRY"', prompt)

    def test_provider_budget_reservation_is_bounded_by_persisted_remaining_steps(self):
        reserved = []
        class Client:
            def reserve_task_budget(self, *, max_steps):
                reserved.append(max_steps)
        state = self._state(maximum=70)
        task_runtime._reserve_task_provider_budget(state, Client())
        self.assertEqual(reserved, [64])
        state.active_entities["execution_budget"]["started_steps"] = 68
        task_runtime._reserve_task_provider_budget(state, Client())
        self.assertEqual(reserved, [64, 2])
        state.active_entities["execution_budget"]["started_steps"] = 70
        task_runtime._reserve_task_provider_budget(state, Client())
        self.assertEqual(reserved, [64, 2])
        self.assertEqual(state.active_entities["execution_budget"]["max_steps"], 70)

    def test_multiple_observation_replans_share_the_task_budget(self):
        state = self._state(maximum=4)
        calls, _ = self._run(state, [
            self._replacement(("second", "stock.second", ["initial"])),
            self._replacement(("third", "stock.third", ["second"])),
            self._replacement(("fourth", "stock.fourth", ["third"])),
            {"decision": "complete", "reason": "All required sources observed"},
        ])
        self.assertEqual(calls, ["initial", "second", "third", "fourth"])
        self.assertEqual(state.status, "complete")
        self.assertEqual(state.active_entities["execution_budget"]["applied_replans"], 3)
        restored = AgentSessionState.from_dict(state.to_dict())
        self.assertEqual(restored.active_entities["execution_budget"], state.active_entities["execution_budget"])

    def test_exhausted_step_budget_cannot_turn_a_requested_replan_into_completion(self):
        state = self._state(maximum=1)
        calls, _ = self._run(state, [self._replacement(("second", "stock.second", ["initial"]))])
        self.assertEqual(calls, ["initial"])
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.active_entities["goal_progress"]["reason"], "execution_budget_exhausted")
        self.assertFalse(state.active_entities["goal_progress"]["complete"])
        self.assertIn("tamamlanmadı", task_runtime._finalize_task_answer(state))

    def test_idle_continue_is_not_a_model_completion_decision(self):
        state = self._state()
        self._run(state, [{"decision": "continue", "reason": "More work is required"}])
        self.assertEqual(state.status, "failed")
        row = state.active_entities["goal_evaluations"][-1]
        self.assertEqual(row["decision"], "continue")
        self.assertFalse(row["applied"])
        self.assertEqual(state.active_entities["response_synthesis"]["final_source"], "typed_goal_incomplete")

    def test_invalid_final_progress_decision_cannot_complete_an_empty_queue(self):
        state = self._state()
        self._run(state, [{"decision": "unsupported"}])
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.active_entities["goal_progress"]["reason"], "goal_evaluator_failed_existing_plan_continues")

    def test_declared_missing_field_blocks_model_completion(self):
        state = self._state()
        self._run(state, [{"decision": "complete", "reason": "Done"}], results={"initial": {"unrelated": 1}})
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.active_entities["goal_progress"]["reason"], "declared_completion_evidence_missing")
        self.assertFalse(state.active_entities["goal_evaluations"][-1]["expected_evidence_status"]["count"]["observed"])

    def test_authoritative_empty_collection_is_observed_not_missing(self):
        state = self._state()
        state.remaining_steps[0].expected_evidence = ["records"]
        self._run(state, [{"decision": "complete", "reason": "No matching records"}], results={"initial": {"records": []}})
        self.assertEqual(state.status, "complete")
        evidence = state.active_entities["goal_evaluations"][-1]["expected_evidence_status"]["records"]
        self.assertTrue(evidence["observed"])
        self.assertFalse(evidence["present"])
        self.assertEqual(evidence["count"], 0)

    def test_resuming_cannot_reset_an_exhausted_persisted_step_budget(self):
        state = self._state(maximum=1)
        state.active_entities["execution_budget"]["started_steps"] = 1
        state = AgentSessionState.from_dict(state.to_dict())
        calls, planner = self._run(state, [])
        self.assertEqual(calls, [])
        self.assertEqual(planner.calls, [])
        self.assertEqual(state.status, "failed")
        self.assertEqual(len(state.remaining_steps), 1)

    def test_verified_execute_readback_can_complete_after_a_previous_continue(self):
        state = self._state()
        state.remaining_steps = []
        state.active_entities["goal_evaluations"] = [{"decision": "continue", "applied": False, "model_invoked": True}]
        state.add_observation(Observation.create(
            domain="stock", operation_name="stock.approved_action", success=True,
            facts={"phase": "execute_readback", "verified": True}, source="execute_approved_operation",
        ))
        task_runtime._complete_state_if_idle(state)
        self.assertEqual(state.status, "complete")

    def test_catalog_discovery_is_visible_and_compiles_as_read_in_every_domain(self):
        from AI.processors.tools import available_tools
        discovery = available_tools()["operations.discover"]
        for domain in ("orders", "stock", "finance", "web"):
            with self.subTest(domain=domain):
                candidates = task_runtime._planner_operation_candidates(domain, "Inspect business evidence", limit=3)
                self.assertIn("operations.discover", candidates)
                accepted, rejected = task_runtime._validate_direct_plan_specs(
                    domain, [{"id": "discover", "operation_id": "operations.discover", "arguments": {}, "depends_on": []}],
                    "Inspect business evidence", allowed_operations={"operations.discover": discovery}, max_steps=1,
                )
                self.assertEqual(rejected, [])
                self.assertEqual([step["id"] for step in accepted], ["discover"])

    def test_general_task_plan_can_select_a_real_operation_without_a_domain_template(self):
        def planner(_prompt):
            return json.dumps({"steps": [{
                "id": "source", "operation_id": "stock.first", "arguments": {},
                "depends_on": [], "expected_evidence": ["count"],
            }]})
        with patch("AI.processors.tools.available_tools", return_value=self.registry):
            step_ids, metadata = task_runtime._domain_task_plan(
                "general", "Inspect authoritative source", planner_client=planner, max_steps=4,
                turn_interpretation={"valid": True, "mode": "inspect", "intent_kind": "data_read"},
            )
        self.assertEqual(step_ids, ["source"])
        self.assertEqual(metadata["source"], "llm_direct")
        self.assertEqual(metadata["step_specs"][0]["operation_domain"], "stock")
        self.assertEqual(metadata["fallback_step_ids"], [])

    def test_discovery_only_plan_defers_required_business_domain_reads(self):
        from AI.processors.tools import available_tools
        discovery = available_tools()["operations.discover"]
        def planner(_prompt):
            return json.dumps({"steps": [{
                "id": "catalog", "operation_id": "operations.discover", "arguments": {},
                "depends_on": [], "expected_evidence": ["operations"],
            }]})
        with patch("AI.processors.tools.available_tools", return_value={"operations.discover": discovery}):
            step_ids, metadata = task_runtime._domain_task_plan(
                "stock", "stok ve finans kaynaklarını incele", planner_client=planner, max_steps=4,
                turn_interpretation={"valid": True, "mode": "inspect", "intent_kind": "data_read",
                                     "semantic_contract": {"entity": "stock", "metric": "count"}},
            )
        self.assertEqual(step_ids, ["catalog"])
        self.assertTrue(metadata["discovery_only_plan"])

    def test_discovered_cross_domain_operations_are_available_to_observation_replanning(self):
        from AI.processors.tools import available_tools
        discovery = available_tools()["operations.discover"]
        registry = {**self.registry, "operations.discover": discovery}
        state = self._state(maximum=2)
        step = state.remaining_steps[0]
        step.operation_candidates = ["operations.discover"]
        step.operation_domain = "operations"
        step.expected_evidence = ["operations"]
        state.active_domain = "orders"
        replies = iter([
            self._replacement(("stock_read", "stock.second", ["initial"])),
            {"decision": "complete", "reason": "Observed exact source"},
        ])
        def planner(_prompt):
            return json.dumps(next(replies))
        with patch("AI.processors.tools.available_tools", return_value=registry), \
                patch.object(task_runtime, "_planner_operation_candidates", return_value={"operations.discover": discovery}), \
                patch.object(task_runtime, "_run_bound_domain_read_step", side_effect=lambda _state, selected, **_options: Result.ok("Observed", data={
                    "tool_call": {"tool": selected.operation_candidates[0]},
                    "tool_result": {"operations": [{"operation_id": "stock.second"}]} if selected.step_id == "initial" else {"count": 3},
                })):
            task_runtime._run_remaining_steps(state, planner_client=planner, chat_client=None, db_name="unused.sqlite3")
        self.assertEqual([selected.tool_names for selected in state.completed_steps], [["operations.discover"], ["stock.second"]])
        self.assertEqual(state.status, "complete")

    def test_discovery_catalog_alone_cannot_complete_the_user_work(self):
        from AI.processors.tools import available_tools
        state = self._state()
        step = state.remaining_steps[0]
        step.operation_candidates = ["operations.discover"]
        step.operation_domain = "operations"
        step.expected_evidence = ["operations"]
        self.registry["operations.discover"] = available_tools()["operations.discover"]
        self._run(state, [{"decision": "complete", "reason": "Catalog read"}], results={"initial": {"operations": []}})
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.active_entities["goal_progress"]["reason"], "operation_discovery_is_not_goal_completion")

    def _report_source(self, *, operation="stock.first", result=None):
        source = AgentTaskStep(
            index=1, step_id="read_source", prompt="Read", objective="Read",
            operation_candidates=[operation], operation_domain="stock", status="completed",
            verification_status="observed", tool_names=[operation],
            result_data={"tool_result": {"rows": [{"amount": 12}], "currency": "TRY"}},
        )
        state = AgentSessionState(goal="Create a source-bound report", active_domain="general", status="running")
        state.completed_steps = [source]
        step = AgentTaskStep(
            index=2, step_id="report", prompt=state.goal, objective=state.goal,
            operation_candidates=["reports.build_snapshot"], operation_domain="reports", depends_on=[source.step_id],
            arguments={"title": "Source report", "sources": [{
                "source_id": "source", "source_step_id": source.step_id, "operation_id": operation,
                "result": result if result is not None else {"$from_step": source.step_id, "path": "tool_result"},
            }], "sheets": [{"name": "Data", "source_id": "source", "rows_path": "rows", "columns": [
                {"key": "amount", "label": "Amount", "source_path": "amount", "data_type": "number"},
            ]}]},
        )
        return state, step

    def test_report_builder_requires_exact_completed_read_source_binding(self):
        from AI.processors.tools import available_tools
        builder = available_tools()["reports.build_snapshot"]
        state, step = self._report_source()
        with patch("AI.processors.tools.available_tools", return_value=self.registry):
            arguments, problems, bindings = task_runtime._resolve_step_arguments(state, step, builder)
        self.assertEqual(problems, [])
        self.assertEqual(bindings["sources[0].result"], "read_source:tool_result")
        self.assertEqual(arguments["sources"][0]["result"], state.completed_steps[0].result_data["tool_result"])

    def test_literal_report_source_and_mismatched_operation_are_rejected_before_handler(self):
        from AI.processors.tools import available_tools
        builder = available_tools()["reports.build_snapshot"]
        guarded_handler = Mock(side_effect=AssertionError("Untrusted source reached report builder"))
        builder = replace(builder, handler=guarded_handler)
        for variation in ("literal", "wrong_operation", "failed_read", "unverified_read"):
            with self.subTest(variation=variation):
                state, step = self._report_source(result={"rows": [{"amount": 999}]} if variation == "literal" else None)
                if variation == "wrong_operation":
                    step.arguments["sources"][0]["operation_id"] = "stock.second"
                elif variation == "failed_read":
                    state.completed_steps[0].status = "failed"
                elif variation == "unverified_read":
                    state.completed_steps[0].verification_status = "pending"
                with patch("AI.processors.tools.available_tools", return_value={**self.registry, builder.name: builder}):
                    result = task_runtime._run_bound_domain_read_step(state, step, db_name="unused.sqlite3")
                self.assertFalse(result.success)
                self.assertTrue(result.data["argument_problems"])
        guarded_handler.assert_not_called()

    def test_model_literal_report_source_invalidates_the_whole_direct_plan(self):
        from AI.processors.tools import available_tools
        builder = available_tools()["reports.build_snapshot"]
        _state, report = self._report_source(result={"rows": [{"amount": 999}]})
        registry = {**self.registry, builder.name: builder}
        accepted, rejected = task_runtime._validate_direct_plan_specs(
            "general", [
                {"id": "read_source", "operation_id": "stock.first", "arguments": {}, "depends_on": []},
                {"id": "report", "operation_id": builder.name, "arguments": report.arguments, "depends_on": ["read_source"]},
            ], report.prompt, allowed_operations=registry, max_steps=4,
        )
        self.assertEqual(accepted, [])
        self.assertIn("report", rejected)

    def test_report_export_requires_exact_builder_snapshot_lineage(self):
        from AI.processors.tools import available_tools
        tool = available_tools()["reports.xlsx.prepare"]
        state, _read = self._report_source()
        source = state.completed_steps[0]
        source.tool_names = ["reports.build_snapshot"]
        source.result_data = {"tool_result": {"report_snapshot": {"snapshot_id": "trusted", "content_hash": "hash"}}}
        step = AgentTaskStep(
            index=2, step_id="export", prompt="Export", objective="Export",
            operation_candidates=[tool.name], operation_domain="reports", depends_on=[source.step_id],
            arguments={"report_snapshot": {"$from_step": source.step_id, "path": "tool_result.report_snapshot"}},
        )
        _args, problems, _bindings = task_runtime._resolve_step_arguments(state, step, tool)
        self.assertEqual(problems, [])
        source.tool_names = ["stock.first"]
        _args, problems, _bindings = task_runtime._resolve_step_arguments(state, step, tool)
        self.assertIn("arguments.report_snapshot:binding_builder_receipt_invalid", problems)
        step.arguments["report_snapshot"] = {"snapshot_id": "forged", "content_hash": "hash"}
        _args, problems, _bindings = task_runtime._resolve_step_arguments(state, step, tool)
        self.assertIn("arguments.report_snapshot:binding_requires_builder_snapshot", problems)

    @staticmethod
    def _deferred_contract():
        return {"deferred_calculation": {
            "status": "pending", "required_calculation_count": 1, "comparison_required": False,
            "expected_calculations": [{"operator": "subtract", "result_kind": "amount", "operand_refs": ["orders.revenue_total", "orders.revenue_total"]}],
        }}

    def test_raw_read_cannot_complete_a_deferred_calculation_obligation(self):
        state = self._state()
        state.active_entities["turn_interpretation"] = {"semantic_contract": self._deferred_contract()}
        self._run(state, [{"decision": "complete", "reason": "Raw numbers collected"}])
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.active_entities["goal_progress"]["unmet_goal_obligations"], ["deferred_source_bound_calculation_missing"])
        self.assertFalse(state.active_entities["goal_obligations"][0]["fulfilled"])

    def test_deferred_calculation_requires_matching_operator_unit_and_source_metric(self):
        for variation in ("correct", "wrong_operator", "wrong_unit", "wrong_metric", "unverified"):
            with self.subTest(variation=variation):
                state = self._state()
                state.active_entities["turn_interpretation"] = {"semantic_contract": self._deferred_contract()}
                row = {
                    "operator": "add" if variation == "wrong_operator" else "subtract",
                    "result_kind": "scalar" if variation == "wrong_unit" else "amount",
                    "verified": variation != "unverified", "evidence_hash": "verified-arithmetic",
                    "source_receipts": [{"source_step_id": "current"}, {"source_step_id": "prior"}],
                    "operand_receipts": [
                        {"operation_id": "stock.first" if variation == "wrong_metric" else "orders.revenue_total", "path": "estimated_revenue"},
                        {"operation_id": "orders.revenue_total", "path": "estimated_revenue"},
                    ],
                }
                state.completed_steps = [AgentTaskStep(
                    index=1, step_id="calculation", prompt="Compute", status="completed", verification_status="observed",
                    tool_names=["analysis.calculate"], result_data={"tool_result": {"verified": True, "evidence_hash": "source-bound-receipt", "verified_calculations": [row]}},
                )]
                with patch("AI.processors.observation_analysis_evidence.verified_observation_calculations", return_value=[row] if row["verified"] else []):
                    from AI.processors.semantic_verifier import verify_calculation_goal_semantics
                    verify_calculation_goal_semantics(state, verifier_client=lambda _prompt: json.dumps({
                        "verdict": "allow", "objective_aligned": True, "requested_calculations_complete": True,
                        "scope_aligned": True, "periods_aligned": True, "units_aligned": True,
                        "comparison_satisfied": False, "accepted_evidence_hashes": [row["evidence_hash"]],
                        "requested_calculation_count": 1, "requested_result_kinds": ["amount"],
                        "period_relations": [], "reason": "This is the requested calculation",
                    }))
                    self.assertEqual(task_runtime._unmet_goal_obligations(state), [] if variation == "correct" else ["deferred_source_bound_calculation_missing"])
                self.assertEqual(task_runtime._unmet_goal_obligations(state), ["deferred_source_bound_calculation_missing"])

    def test_unread_period_formula_is_deferred_without_erasing_completion_obligation(self):
        payload = {
            "mode": "inspect", "domain": "orders", "intent_kind": "data_read", "objective": "Compare current and prior revenue",
            "request_shape": "focused_analysis", "entity": "order", "metric": "derived", "period": "last7d",
            "record_scope": "all_matching", "information_source": "local_business_data", "operation_policy": "allow_new_operations",
            "requires_clarification": False, "clarification": "", "missing_input": "none",
            "comparison_policy": "not_requested", "requested_fields": ["amount", "calculation"],
            "calculation_grouping": "single_result", "calculation_count": 1,
            "derived_calculation": {"operator": "subtract", "operands": [{"ref": "orders.revenue_total"}, {"ref": "orders.revenue_total", "offset": -1}],
                                    "result_kind": "amount", "precision": 2, "show_work": True},
        }
        calls = []
        def planner(prompt):
            calls.append(prompt)
            return json.dumps(payload)
        result = task_runtime.interpret_agent_turn("Son 7 günlük ciro ile önceki 7 günlük ciro farkını hesapla", planner_client=planner)
        self.assertTrue(result.success, result.data)
        self.assertTrue(result.data["valid"], result.data)
        deferred = result.data["semantic_contract"]["deferred_calculation"]
        self.assertEqual(deferred["status"], "pending")
        self.assertEqual(deferred["required_calculation_count"], 1)
        self.assertEqual(deferred["expected_calculations"][0]["operand_refs"], ["orders.revenue_total", "orders.revenue_total"])
        self.assertFalse(result.data.get("formula_repair_invoked", False))

    def test_upfront_invented_literal_is_deferred_for_new_reads_but_existing_only_stays_closed(self):
        payload = {
            "mode": "inspect", "domain": "orders", "intent_kind": "data_read", "objective": "Research business changes",
            "request_shape": "focused_analysis", "entity": "order", "metric": "derived", "period": "last7d",
            "record_scope": "all_matching", "information_source": "local_business_data", "operation_policy": "allow_new_operations",
            "requires_clarification": False, "clarification": "", "missing_input": "none", "comparison_policy": "not_requested",
            "requested_fields": ["amount", "calculation"], "calculation_grouping": "single_result", "calculation_count": 1,
            "derived_calculation": {"operator": "subtract", "operands": [{"ref": "orders.revenue_total"}, {"ref": "literal", "value": 0}],
                                    "result_kind": "amount", "precision": 2, "show_work": True},
        }
        result = task_runtime.interpret_agent_turn(
            "Son dönemin cirosu ile önceki dönemin cirosu arasındaki farkı hesapla", planner_client=lambda _prompt: json.dumps(payload),
        )
        self.assertTrue(result.success, result.data)
        self.assertTrue(result.data["valid"], result.data)
        self.assertEqual(result.data["operation_policy"], "allow_new_operations")
        deferred = result.data["semantic_contract"]["deferred_calculation"]
        self.assertEqual(deferred["expected_calculations"], [])
        self.assertEqual(deferred["cardinality_authority"], "provisional_initial_interpretation")
        self.assertIn("literal_not_in_current_message:0", deferred["validation_reason_codes"])
        forbidden = task_runtime.interpret_agent_turn(
            "Yeni işlem yapma; sadece mevcut gözlemlerden iki dönemin ciro farkını hesapla",
            planner_client=lambda _prompt: json.dumps({**payload, "operation_policy": "existing_observations_only"}),
        )
        self.assertFalse(forbidden.success)
        self.assertFalse(forbidden.data["valid"])
        historical = task_runtime.interpret_agent_turn(
            "İki dönemin ciro farkını açıkla",
            planner_client=lambda _prompt: json.dumps({**payload, "operation_policy": "existing_observations_only"}),
        )
        self.assertEqual(historical.data["operation_policy"], "existing_observations_only")

    @staticmethod
    def _calculated_goal_state(*, same_period=False, required_count=1):
        from AI.processors.analysis_operations import calculate_observations

        state = AgentSessionState(goal="Compare current seven days with the immediately preceding seven days", active_domain="general")
        state.active_entities["turn_interpretation"] = {
            "objective": state.goal, "semantic_contract": {"deferred_calculation": {
                "status": "pending", "required_calculation_count": required_count,
                "comparison_required": False, "expected_calculations": [], "required_result_kinds": ["amount"],
            }},
        }
        reads = [
            ("current", {"estimated_revenue": 150, "currency": "TRY", "api_account_ids": [7],
                         "environment_by_account": {"7": "pilot"}, "start_date": "2026-10-02", "end_date": "2026-10-08"}),
            ("prior", {"estimated_revenue": 100, "currency": "TRY", "api_account_ids": [7],
                       "environment_by_account": {"7": "pilot"}, "start_date": "2026-10-02" if same_period else "2026-09-25",
                       "end_date": "2026-10-08" if same_period else "2026-10-01"}),
        ]
        for index, (identity, payload) in enumerate(reads, 1):
            state.completed_steps.append(AgentTaskStep(index=index, step_id=identity, prompt="Read authoritative sales",
                status="completed", verification_status="observed", tool_names=["orders.revenue_total"],
                result_data={"tool_result": payload}))
        result = calculate_observations(
            sources=[{"source_id": identity, "source_step_id": identity, "operation_id": "orders.revenue_total", "result": payload}
                     for identity, payload in reads],
            calculations=[{"calculation_id": "revenue_change", "operator": "subtract",
                           "operands": [{"source_id": "current", "path": "estimated_revenue"},
                                        {"source_id": "prior", "path": "estimated_revenue"}]}],
        )
        assert result.success, result.data
        state.completed_steps.append(AgentTaskStep(index=3, step_id="calculate", prompt="Calculate the requested change",
            status="completed", verification_status="observed", tool_names=["analysis.calculate"], result_data={"tool_result": result.data}))
        return state

    @staticmethod
    def _calculation_goal_verdict(state, **changes):
        from AI.processors.observation_analysis_evidence import verified_observation_calculations

        verdict = {
            "verdict": "allow", "objective_aligned": True, "requested_calculations_complete": True,
            "scope_aligned": True, "periods_aligned": True, "units_aligned": True, "comparison_satisfied": True,
            "accepted_evidence_hashes": [row["evidence_hash"] for row in verified_observation_calculations(state)],
            "requested_calculation_count": 1, "requested_result_kinds": ["amount"],
            "period_relations": [{"left_source_step_id": "current", "right_source_step_id": "prior", "relation": "previous_equal_period"}],
            "reason": "The calculation compares the requested account and two observed equal periods",
        }
        verdict.update(changes)
        return verdict

    def test_coarse_goal_requires_bound_semantic_verdict_after_independent_arithmetic(self):
        from AI.processors.semantic_verifier import verify_calculation_goal_semantics

        state = self._calculated_goal_state()
        self.assertEqual(task_runtime._unmet_goal_obligations(state), ["deferred_source_bound_calculation_missing"])
        prompts = []
        def planner(prompt):
            prompts.append(prompt)
            return json.dumps(self._calculation_goal_verdict(state))
        receipt = verify_calculation_goal_semantics(state, verifier_client=planner)
        self.assertTrue(receipt["allowed"], receipt)
        self.assertEqual(task_runtime._unmet_goal_obligations(state), [])
        self.assertIn(state.goal, prompts[0])
        self.assertIn('"environment_by_account": {"7": "pilot"}', prompts[0])
        self.assertIn('"start_date": "2026-09-25"', prompts[0])
        verify_calculation_goal_semantics(state, verifier_client=planner)
        self.assertEqual(len(prompts), 1)
        state.goal = "Calculate stock capital instead"
        self.assertEqual(task_runtime._unmet_goal_obligations(state), ["deferred_source_bound_calculation_missing"])

    def test_same_period_cannot_pass_an_allowed_previous_period_verdict(self):
        from AI.processors.semantic_verifier import verify_calculation_goal_semantics

        state = self._calculated_goal_state(same_period=True)
        receipt = verify_calculation_goal_semantics(state, verifier_client=lambda _prompt: json.dumps(self._calculation_goal_verdict(state)))
        self.assertFalse(receipt["allowed"])
        self.assertIn("calculation_previous_equal_period_not_observed", receipt["reason_codes"])
        self.assertEqual(task_runtime._unmet_goal_obligations(state), ["deferred_source_bound_calculation_missing"])

    def test_previous_equal_period_verifies_both_source_orders_without_reordering_arithmetic(self):
        from AI.processors.observation_analysis_evidence import verified_observation_calculations
        from AI.processors.semantic_verifier import verify_calculation_goal_semantics

        for left, right in (("current", "prior"), ("prior", "current")):
            with self.subTest(left=left):
                state = self._calculated_goal_state()
                before = verified_observation_calculations(state)
                receipt = verify_calculation_goal_semantics(state, verifier_client=lambda _prompt: json.dumps(
                    self._calculation_goal_verdict(state, period_relations=[{
                        "left_source_step_id": left, "right_source_step_id": right, "relation": "previous_equal_period",
                    }])))
                self.assertTrue(receipt["allowed"], receipt)
                self.assertEqual(receipt["observed_period_relations"][0]["prior_source_step_id"], "prior")
                self.assertEqual(receipt["observed_period_relations"][0]["current_source_step_id"], "current")
                self.assertEqual(verified_observation_calculations(state), before)
                self.assertEqual(task_runtime._unmet_goal_obligations(state), [])

    def test_period_pair_order_cannot_hide_nonadjacent_unequal_overlapping_or_unbound_sources(self):
        from AI.processors.semantic_verifier import _calculation_period_relation_problems

        current = {"start_ms": 1790888400000, "end_ms": 1791493199999}
        valid_prior = {"start_ms": 1790283600000, "end_ms": 1790888399999}
        def evidence(prior):
            return [{"source_receipts": [{"source_step_id": "current", "period": current},
                                          {"source_step_id": "prior", "period": prior}],
                     "operand_receipts": [{"source_step_id": "current"}, {"source_step_id": "prior"}]}]
        for left, right in (("current", "prior"), ("prior", "current")):
            verdict = {"period_relations": [{"left_source_step_id": left, "right_source_step_id": right,
                                             "relation": "previous_equal_period"}]}
            self.assertEqual(_calculation_period_relation_problems(verdict, evidence(valid_prior)), [])
            for prior in (current, {**valid_prior, "end_ms": valid_prior["end_ms"] - 86400000},
                          {**valid_prior, "start_ms": valid_prior["start_ms"] - 86400000},
                          {**valid_prior, "end_ms": current["start_ms"] + 1},
                          {"start_ms": float("-inf"), "end_ms": float("inf")}):
                with self.subTest(left=left, prior=prior):
                    self.assertTrue(_calculation_period_relation_problems(verdict, evidence(prior)))
            unbound = evidence(valid_prior)
            unbound[0]["operand_receipts"] = [{"source_step_id": "current"}]
            self.assertIn("calculation_period_sources_not_bound", _calculation_period_relation_problems(verdict, unbound))

    def test_reversed_period_relation_does_not_authorize_changed_account_scope(self):
        from AI.processors.semantic_verifier import verify_calculation_goal_semantics

        state = self._calculated_goal_state()
        verdict = self._calculation_goal_verdict(state, period_relations=[{
            "left_source_step_id": "prior", "right_source_step_id": "current", "relation": "previous_equal_period",
        }])
        state.completed_steps[1].result_data["tool_result"]["api_account_ids"] = [999]
        client = Mock(return_value=json.dumps(verdict))
        receipt = verify_calculation_goal_semantics(state, verifier_client=client)
        self.assertFalse(receipt["allowed"])
        self.assertIn("calculation_arithmetic_proof_missing", receipt["reason_codes"])
        client.assert_not_called()

    def test_independent_proof_drift_invalidates_a_previously_allowed_goal_verdict(self):
        from AI.processors.semantic_verifier import verify_calculation_goal_semantics

        state = self._calculated_goal_state()
        verify_calculation_goal_semantics(state, verifier_client=lambda _prompt: json.dumps(self._calculation_goal_verdict(state)))
        state.completed_steps[0].result_data["tool_result"]["api_account_ids"] = [999]
        self.assertEqual(task_runtime._unmet_goal_obligations(state), ["deferred_source_bound_calculation_missing"])
        planner = Mock(side_effect=AssertionError("No unverifiable proof sent to the model"))
        receipt = verify_calculation_goal_semantics(state, verifier_client=planner)
        self.assertFalse(receipt["allowed"])
        planner.assert_not_called()

    def test_unrelated_calculation_denied_by_objective_verdict_cannot_fulfill_goal(self):
        from AI.processors.semantic_verifier import verify_calculation_goal_semantics

        state = self._calculated_goal_state()
        receipt = verify_calculation_goal_semantics(state, verifier_client=lambda _prompt: json.dumps(
            self._calculation_goal_verdict(state, verdict="deny", objective_aligned=False, reason="Goal requested stock, not revenue")))
        self.assertFalse(receipt["allowed"])
        self.assertEqual(task_runtime._unmet_goal_obligations(state), ["deferred_source_bound_calculation_missing"])

    def test_calculation_verdict_has_one_shape_repair_and_provider_failure_stays_partial(self):
        from AI.processors.semantic_verifier import verify_calculation_goal_semantics

        state = self._calculated_goal_state()
        replies = iter(["{}", json.dumps(self._calculation_goal_verdict(state))])
        calls = []
        def planner(prompt):
            calls.append(prompt)
            return next(replies)
        self.assertTrue(verify_calculation_goal_semantics(state, verifier_client=planner)["allowed"])
        self.assertEqual(len(calls), 2)
        for responses in (["{}", "{}"], [RuntimeError("Provider unavailable")]):
            with self.subTest(responses=str(responses)):
                state = self._calculated_goal_state()
                replies = iter(responses)
                calls = []
                def planner(prompt):
                    calls.append(prompt)
                    reply = next(replies)
                    if isinstance(reply, Exception):
                        raise reply
                    return reply
                receipt = verify_calculation_goal_semantics(state, verifier_client=planner)
                self.assertFalse(receipt["allowed"])
                task_runtime._stop_incomplete_task(state, "deferred_source_bound_calculation_missing")
                self.assertEqual(state.status, "failed")
                self.assertIn("tamamlanmad", task_runtime._finalize_task_answer(state))
                self.assertEqual(len(calls), len(responses))

    def test_allowed_coarse_verdict_cannot_replace_required_count_or_boolean_comparison(self):
        from AI.processors.semantic_verifier import verify_calculation_goal_semantics

        for variation in ("count", "comparison", "forged_hash"):
            with self.subTest(variation=variation):
                state = self._calculated_goal_state(required_count=2 if variation == "count" else 1)
                if variation == "comparison":
                    state.active_entities["turn_interpretation"]["semantic_contract"]["deferred_calculation"]["comparison_required"] = True
                changes = {"accepted_evidence_hashes": ["invented-proof"]} if variation == "forged_hash" else {}
                verify_calculation_goal_semantics(state, verifier_client=lambda _prompt: json.dumps(self._calculation_goal_verdict(state, **changes)))
                self.assertEqual(task_runtime._unmet_goal_obligations(state), ["deferred_source_bound_calculation_missing"])

    def test_general_new_read_can_preserve_typed_calculation_goal_without_upfront_formula(self):
        payload = {
            "mode": "inspect", "domain": "general", "intent_kind": "data_read", "objective": "Research two periods across business domains",
            "request_shape": "broad_analysis", "entity": "general", "metric": "summary", "period": "last7d",
            "record_scope": "all_matching", "information_source": "local_business_data", "operation_policy": "allow_new_operations",
            "requires_clarification": False, "clarification": "", "missing_input": "none", "comparison_policy": "not_requested",
            "requested_fields": ["amount", "calculation"], "calculation_grouping": "single_result", "calculation_count": 1,
            "derived_calculations": [],
        }
        result = task_runtime.interpret_agent_turn("Research these two business periods and explain the changes", planner_client=lambda _prompt: json.dumps(payload))
        self.assertTrue(result.success, result.data)
        self.assertTrue(result.data["valid"], result.data)
        deferred = result.data["semantic_contract"]["deferred_calculation"]
        self.assertEqual(deferred["expected_calculations"], [])
        self.assertEqual(deferred["required_calculation_count"], 1)

    def test_post_read_goal_verdict_can_correct_provisional_formula_count_but_not_strict_refs(self):
        from AI.processors.semantic_verifier import verify_calculation_goal_semantics

        state = self._calculated_goal_state(required_count=3)
        deferred = state.active_entities["turn_interpretation"]["semantic_contract"]["deferred_calculation"]
        deferred["cardinality_authority"] = "provisional_initial_interpretation"
        verify_calculation_goal_semantics(state, verifier_client=lambda _prompt: json.dumps(self._calculation_goal_verdict(state)))
        self.assertEqual(task_runtime._unmet_goal_obligations(state), [])
        self.assertEqual(state.active_entities["goal_obligations"][0]["required_calculation_count"], 1)
        deferred["expected_calculations"] = [{"operator": "divide", "result_kind": "amount_per_order", "operand_refs": ["orders.revenue_total", "orders.total_count"]}]
        verify_calculation_goal_semantics(state, verifier_client=lambda _prompt: json.dumps(self._calculation_goal_verdict(state)))
        self.assertEqual(task_runtime._unmet_goal_obligations(state), ["deferred_source_bound_calculation_missing"])

    def test_general_store_anchor_keeps_business_sources_and_registered_owner_separate(self):
        from AI.processors.semantic_contracts import validate_business_read_arguments
        from AI.processors.turn_evidence import validate_record_population

        payload = {
            "mode": "inspect", "domain": "general", "intent_kind": "data_read", "objective": "Analyze sales, stock and finance for one store",
            "request_shape": "broad_analysis", "entity": "marketplace_account", "metric": "summary", "period": "last7d",
            "record_scope": "all_matching", "information_source": "local_business_data", "operation_policy": "allow_new_operations",
            "requires_clarification": False, "clarification": "", "missing_input": "none", "comparison_policy": "not_requested",
            "requested_fields": ["amount", "scope"], "calculation_grouping": "none", "calculation_count": 0,
        }
        result = task_runtime.interpret_agent_turn("Analyze sales, stock and finance for one store", planner_client=lambda _prompt: json.dumps(payload))
        self.assertTrue(result.success, result.data)
        contract = result.data["semantic_contract"]
        self.assertEqual(contract["scope_anchor"], {"entity": "marketplace_account", "owner_domain": "marketplaces"})
        self.assertEqual(contract["period"], "last7d")
        self.assertEqual(validate_business_read_arguments(contract, "orders.revenue_total", {}), ())
        for shape in ("scalar", "record_list", "record_detail"):
            with self.subTest(shape=shape), self.assertRaisesRegex(ValueError, "entity_owner_mismatch"):
                validate_record_population({"domain": "general", "intent_kind": "data_read", "request_shape": shape,
                                            "semantic_contract": {"entity": "marketplace_account"}})

    def test_ranked_report_export_includes_required_builder_schema_within_catalog_budget(self):
        from AI.processors.operation_catalog import build_operation_catalog
        from AI.processors.tools import available_tools

        catalog = build_operation_catalog(available_tools(), include_manual=False)
        export = catalog["reports.xlsx.prepare"]
        with patch("AI.processors.operation_catalog.retrieve_operation_candidates", return_value=[export]):
            candidates = task_runtime._planner_operation_candidates("general", "Export observed data", limit=3)
        self.assertEqual(set(candidates), {"reports.xlsx.prepare", "reports.build_snapshot", "operations.discover"})
        self.assertEqual(list(candidates)[-1], "operations.discover")
        prompt = task_runtime._orders_plan_prompt("Export observed data", 3, operation_candidates=candidates)
        self.assertIn("input_source_requirements", prompt)
        self.assertIn("tool_result.report_snapshot", prompt)
        self.assertIn("yalniz kesif adimini kur", prompt)
        self.assertIn('"source_step_id"', prompt)

    def test_calculation_observation_invokes_bound_goal_verifier_before_completion(self):
        for allowed in (True, False):
            with self.subTest(allowed=allowed):
                state = self._calculated_goal_state()
                step = state.completed_steps[-1]
                step.operation_candidates = ["analysis.calculate"]
                step.operation_domain = "analysis"
                step.expected_evidence = ["verified"]
                observation = Observation.create(domain="analysis", operation_name="analysis.calculate", success=True, facts={"verified": True})
                prompts = []
                def planner(prompt):
                    prompts.append(prompt)
                    if prompt.startswith("OrderScout calculation goal verifier"):
                        return json.dumps(self._calculation_goal_verdict(state, verdict="allow" if allowed else "deny", objective_aligned=allowed))
                    return json.dumps({"decision": "complete", "reason": "Requested work is complete"})
                row = task_runtime._reevaluate_goal_after_observation(state, step, observation, planner_client=planner, max_steps=2, max_replans=2)
                self.assertEqual(row["applied"], allowed)
                self.assertEqual(row["decision"], "complete" if allowed else "continue")
                self.assertEqual(len(prompts), 2)
                self.assertEqual(state.active_entities["calculation_goal_verification"]["allowed"], allowed)

    def test_orders_compiler_preserves_same_operation_with_different_period_scopes(self):
        from AI.processors.tools import available_tools
        registry = available_tools()
        specs = [
            {"id": "current", "operation_id": "orders.revenue_total", "arguments": {"period": "last7d"}, "depends_on": []},
            {"id": "prior", "operation_id": "orders.revenue_total", "arguments": {
                "period": "last7d", "start_date": "2026-09-25", "end_date": "2026-10-01"}, "depends_on": []},
            {"id": "calculate", "operation_id": "analysis.calculate", "arguments": {"sources": [
                {"source_id": identity, "source_step_id": identity, "operation_id": "orders.revenue_total",
                 "result": {"$from_step": identity, "path": "tool_result"}} for identity in ("current", "prior")
            ]}, "depends_on": ["current", "prior"]},
        ]
        ids, compiled, metadata = task_runtime._compile_orders_direct_plan_specs(
            specs, "Compare two periods", allowed_operations=registry, max_steps=3,
            semantic_contract={"metric_requirements": ["revenue_total"]},
        )
        self.assertEqual(ids, ["current", "prior", "calculate"])
        self.assertEqual(compiled[1]["arguments"], specs[1]["arguments"])
        self.assertEqual(compiled[2]["depends_on"], ["current", "prior"])
        self.assertFalse(metadata["deterministic_business_steps_inserted"])

    def test_file_workspace_capability_survives_a_fresh_task_without_exposing_paths(self):
        previous = AgentSessionState(goal="Conversation", active_domain="general")
        previous.active_entities["file_workspace"] = {
            "session_id": previous.session_id,
            "attachments": [{"attachment_id": "att_authorized", "name": "sales.json", "format": "json", "sha256": "hash", "source_path": "PRIVATE-PATH"}],
        }
        fresh = task_runtime._fresh_task_state_from_conversation(goal="Inspect attached data", domain="general", session_state=previous)
        self.assertNotEqual(fresh.session_id, previous.session_id)
        self.assertEqual(fresh.active_entities["file_workspace"]["session_id"], previous.session_id)
        context = task_runtime._planner_typed_context(fresh)
        self.assertIn("att_authorized", json.dumps(context))
        self.assertNotIn("PRIVATE-PATH", json.dumps(context))

    def test_file_read_uses_only_trusted_import_session_and_authorized_attachment_ids(self):
        from AI.processors.tools import available_tools
        tool = available_tools()["files.read"]
        handler = Mock(return_value=Result.ok("Observed imported file", data={"verified": True, "rows": []}))
        tool = replace(tool, handler=handler)
        state = AgentSessionState(goal="Inspect attachment", active_domain="general")
        state.active_entities["file_workspace"] = {"session_id": "trusted-import-owner", "attachments": [{"attachment_id": "att_authorized"}]}
        step = AgentTaskStep(index=1, step_id="read_file", prompt=state.goal, operation_candidates=[tool.name], operation_domain="files",
                             arguments={"attachment_id": "att_authorized", "session_id": "attacker-selected-session"})
        with patch("AI.processors.tools.available_tools", return_value={tool.name: tool}):
            result = task_runtime._run_bound_domain_read_step(state, step, db_name="unused.sqlite3")
        self.assertTrue(result.success, result.data)
        self.assertEqual(handler.call_args.kwargs["session_id"], "trusted-import-owner")
        self.assertEqual(result.data["dependency_bindings"]["session_id"], "trusted_file_workspace.session_id")
        for variation in ("other_attachment", "missing_manifest"):
            with self.subTest(variation=variation):
                handler.reset_mock()
                if variation == "other_attachment":
                    step.arguments["attachment_id"] = "att_other_session"
                else:
                    state.active_entities.pop("file_workspace")
                with patch("AI.processors.tools.available_tools", return_value={tool.name: tool}):
                    result = task_runtime._run_bound_domain_read_step(state, step, db_name="unused.sqlite3")
                self.assertFalse(result.success)
                handler.assert_not_called()

    def test_file_read_plan_does_not_require_the_model_to_select_an_import_session(self):
        from AI.processors.tools import available_tools
        tool = available_tools()["files.read"]
        accepted, rejected = task_runtime._validate_direct_plan_specs(
            "general", [{"id": "read_file", "operation_id": tool.name, "arguments": {"attachment_id": "att_authorized"}, "depends_on": []}],
            "Read attached source", allowed_operations={tool.name: tool}, max_steps=1,
        )
        self.assertEqual(rejected, [])
        self.assertEqual(accepted[0]["arguments"]["session_id"], "runtime_owned_file_workspace")


if __name__ == "__main__":
    unittest.main()
