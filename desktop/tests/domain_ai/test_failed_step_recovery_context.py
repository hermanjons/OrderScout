from __future__ import annotations

import json
from unittest.mock import patch

from AI.processors import task_runtime
from AI.processors.session_state import AgentSessionState, AgentTaskStep, GoalPlan, Observation
from AI.processors.tools import available_tools


def _state():
    state = AgentSessionState(goal="Investigate the observed sales, inventory and recorded finance", active_domain="general", status="running")
    state.active_entities["turn_interpretation"] = {
        "mode": "inspect", "intent_kind": "data_read", "requested_fields": [],
        "semantic_contract": {"read_domains": ["orders", "stock", "finance"]},
    }
    state.active_entities["task_plan"] = {"operation_candidate_ids": ["reports.build_snapshot"]}
    for number, operation, payload in (
        (3, "orders.item_sales_summary", {"rows": [{"product_name": "PRIVATE_PRODUCT_VALUE", "quantity": 4,
                                                  "currency": "TRY", "quantity_unit": "marketplace_item"}],
                                         "start_date_ms": 1791158400000, "end_date_ms": 1791763199999}),
        (5, "stock.inventory_overview", {"rows": [], "company_id": 201, "warehouse_id": 301}),
        (6, "finance.cashflow_summary", {"rows": [], "company_id": 201}),
    ):
        step = AgentTaskStep(index=number, step_id=f"step_{number}", prompt="Observed source", status="completed",
                             verification_status="observed", tool_names=[operation], operation_candidates=[operation],
                             result_data={"tool_result": {"tool": operation, **payload}})
        state.completed_steps.append(step)
    failed = AgentTaskStep(index=10, step_id="retry_1", prompt="Assemble evidence", status="failed",
                           operation_candidates=["reports.build_snapshot"], verification_status="failed",
                           result_message="Gecersiz deger.", result_data={"tool_result": {
                               "reason_codes": ["observation_projection_path_missing:product"],
                               "projection_diagnostic": {"source_step_id": "step_3", "missing_path": "product"},
                           }})
    state.completed_steps.append(failed)
    return state, failed


def _snapshot_spec(*, identity="repair_2", source_step="step_3", operation="orders.item_sales_summary"):
    return {"id": identity, "operation_id": "reports.build_snapshot", "depends_on": [source_step],
            "arguments": {"title": "Observed rows", "sources": [{"source_id": "items", "source_step_id": source_step,
                           "operation_id": operation, "result": {"$from_step": source_step, "path": "tool_result"}}],
                          "sheets": [{"name": "Items", "source_id": "items", "rows_path": "rows",
                                      "columns": [{"key": "product", "label": "Product", "source_path": "product_name",
                                                   "data_type": "string"}]}]},
            "expected_evidence": ["report_snapshot"], "objective": "Repair missing field projection"}


def test_recovery_prompt_retains_actual_source_ids_paths_scope_and_failure_without_cell_values():
    state, failed = _state()
    prompt = task_runtime._domain_replan_prompt(state, failed, max_steps=2,
                                               operation_candidates={"reports.build_snapshot": available_tools()["reports.build_snapshot"]})
    assert '"step_id": "step_5"' in prompt and '"operation_id": "stock.inventory_overview"' in prompt
    assert '"step_id": "step_6"' in prompt and '"operation_id": "finance.cashflow_summary"' in prompt
    assert '"path": "rows[].product_name"' in prompt
    assert '"start_date_ms": 1791158400000' in prompt
    assert "observation_projection_path_missing:product" in prompt
    assert 'Forbidden completed/failed step IDs: ["step_3", "step_5", "step_6", "retry_1"]' in prompt
    assert "PRIVATE_PRODUCT_VALUE" not in prompt
    assert "rows_path zaten baglanmis result'a gore" in prompt


def test_recovery_rejects_misidentified_completed_source_before_any_handler_and_preserves_exact_reason():
    state, failed = _state()
    tool = available_tools()["reports.build_snapshot"]
    wrong = _snapshot_spec(source_step="step_5", operation="finance.cashflow_summary")
    with patch.object(task_runtime, "_planner_operation_candidates", return_value={tool.name: tool}):
        accepted = task_runtime._replan_after_failed_step(state, failed,
            planner_client=lambda prompt: json.dumps({"steps": [wrong], "reason": "Repair projection"}), max_steps=2, max_replans=3)
    assert accepted is False
    rejection = state.active_entities["replans"][-1]
    assert rejection["applied"] is False
    assert any("binding_source_operation_mismatch" in code
               for row in rejection["validation_diagnostics"] for code in row["reason_codes"])
    assert "binding_source_operation_mismatch" in task_runtime._domain_replan_prompt(state, failed, max_steps=2,
                                                                                   operation_candidates={tool.name: tool})


def test_recovery_can_correct_projection_using_same_operation_new_id_and_actual_completed_source():
    state, failed = _state()
    tool = available_tools()["reports.build_snapshot"]
    with patch.object(task_runtime, "_planner_operation_candidates", return_value={tool.name: tool}):
        accepted = task_runtime._replan_after_failed_step(state, failed,
            planner_client=lambda prompt: json.dumps({"steps": [_snapshot_spec()], "reason": "Use observed product_name"}),
            max_steps=2, max_replans=3)
    assert accepted is True, json.dumps(state.active_entities.get("replans"))
    assert state.remaining_steps[0].step_id == "repair_2"
    assert state.remaining_steps[0].depends_on == ["step_3"]
    assert state.remaining_steps[0].arguments["sources"][0]["operation_id"] == "orders.item_sales_summary"
    assert failed.verification_status == "superseded"


def test_failed_source_id_cannot_be_reused_as_a_recovery_node():
    state, failed = _state()
    tool = available_tools()["reports.build_snapshot"]
    with patch.object(task_runtime, "_planner_operation_candidates", return_value={tool.name: tool}):
        accepted = task_runtime._replan_after_failed_step(state, failed,
            planner_client=lambda prompt: json.dumps({"steps": [_snapshot_spec(identity="retry_1")], "reason": "Repair"}),
            max_steps=2, max_replans=3)
    assert accepted is False
    assert state.active_entities["replans"][-1]["validation_diagnostics"]


def test_observation_replan_catalog_keeps_actual_delegation_restrictions_visible_to_model():
    state, failed = _state()
    tool = available_tools()["agent.delegate"]
    observation = Observation.create(domain="orders", operation_name="orders.item_sales_summary", success=True, source="local_db")
    prompt = task_runtime._goal_evaluation_prompt(state, failed, observation, operation_candidates={tool.name: tool}, max_steps=4)
    assert "description=" + task_runtime._compact_text(tool.description)[:1000] in prompt
    assert "agent.delegate" in prompt


def test_execution_persists_argument_binding_failure_for_next_recovery_instead_of_erasing_it():
    state, _ = _state()
    state.completed_steps = state.completed_steps[:-1]
    spec = _snapshot_spec(source_step="step_5", operation="finance.cashflow_summary")
    pending = AgentTaskStep(index=10, step_id="invalid_source", prompt="Assemble report", objective="Assemble report",
                           operation_candidates=["reports.build_snapshot"], operation_domain=available_tools()["reports.build_snapshot"].domain,
                           depends_on=spec["depends_on"], arguments=spec["arguments"], expected_evidence=["report_snapshot"])
    state.add_goal_plan(GoalPlan(goal=state.goal, domain="general", source="llm_direct", steps=[*state.completed_steps, pending]))
    state.remaining_steps = [pending]
    state.active_entities["execution_budget"] = {"contract_version": 1, "max_steps": 4, "started_steps": 3,
                                                "max_replans": 0, "applied_replans": 0}
    task_runtime._run_remaining_steps(state, planner_client=None, chat_client=None, db_name="unused.sqlite3")
    assert pending.status == "failed", json.dumps({"status": state.status, "active": state.active_entities, "remaining": [s.to_dict() for s in state.remaining_steps]})
    assert pending.result_data.get("tool") == "reports.build_snapshot", json.dumps(pending.result_data)
    assert pending.result_data["retryable"] is False
    assert any("binding_source_operation_mismatch" in code for code in pending.result_data["argument_problems"])
    assert not pending.tool_names
