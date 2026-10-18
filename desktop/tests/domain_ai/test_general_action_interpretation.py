"""Current general actions keep their model-authored owner and projection."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from AI.processors import task_runtime, workflow_store
from AI.processors.business_acceptance_fixtures import WORKFLOW_ACCEPTANCE_SPEC, workflow_save_prompt


def _captured_turn(filename="schedule_glm_first_turn_interpretation.json"):
    return json.loads((Path(__file__).parent / "fixtures" /
                       filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename", ["schedule_glm_first_turn_interpretation.json",
                                    "schedule_glm_approval_control_first_turn_interpretation.json"])
@pytest.mark.parametrize("parent_domain", ["general", "orders"])
def test_actual_glm_instruction_package_turn_keeps_general_action_and_reaches_current_proposal(tmp_path, monkeypatch, filename, parent_domain):
    captured = _captured_turn(filename)
    assert captured["scenario_id"] == "workflow_save_prepare"
    assert captured["requested_model"] == captured["actual_model"] == "z-ai/glm-5.3-flash"
    assert captured["fallback_used"] is False
    assert captured["prompt"] == workflow_save_prompt()
    assert task_runtime._goal_has_report_export_intent(captured["prompt"])
    assert task_runtime._contextual_reference_requested(captured["prompt"])
    interpreted = task_runtime.interpret_agent_turn(
        captured["prompt"], planner_client=lambda _: json.dumps(captured["response"], ensure_ascii=False),
    )
    assert interpreted.success, interpreted.message
    current = interpreted.data
    assert current["domain"] == "general"
    assert current["mode"] == "act" and current["intent_kind"] == "action"
    assert current["objective"] == captured["response"]["objective"]
    assert current["requested_fields"] == ["action_result"]
    assert current["turn_contract_provenance"]["initial"]["domain"] == "general"
    assert current["turn_contract_provenance"]["accepted"]["domain"] == "general"
    assert "order_item_quantity_dimension_added" not in current["semantic_corrections"]

    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", tmp_path / "workflow-data")
    prompts = []
    plan = {"steps": [{"id": "prepare_package", "operation_id": "workflows.save.prepare",
        "arguments": {"spec": deepcopy(WORKFLOW_ACCEPTANCE_SPEC), "workflow_id": "pilot-stock-review"},
        "depends_on": [], "objective": "Prepare the exact current instruction package for approval",
        "expected_evidence": ["action", "spec_hash"]}]}
    def planner(prompt):
        prompts.append(prompt)
        if prompt.startswith("OrderScout semantic action verifier"):
            assert 'Canonical runtime domain compatibility: true' in prompt
            assert 'does NOT require literal equality' in prompt
            return json.dumps({"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
                "unwanted_effect": False, "reason": "Only the requested exact instruction package is prepared",
                "configuration_schema_reviews": [{"argument_path": "/spec/parameter_schema",
                    "requested_schema_json": json.dumps(WORKFLOW_ACCEPTANCE_SPEC["parameter_schema"]),
                    "requirement_quotes": [captured["prompt"][:950]]}]})
        return json.dumps(plan, ensure_ascii=False)

    # The Orders variant deliberately changes only the parent classification:
    # a global configuration proposal must remain discoverable and executable.
    execution_turn = deepcopy(current)
    execution_turn["domain"] = parent_domain
    started = task_runtime.run_agent_task(
        captured["prompt"], domain=parent_domain, turn_interpretation=execution_turn,
        planner_client=planner, persist=False, db_name=str(tmp_path / "business.sqlite3"), max_steps=8,
    )
    assert started.success, started.message
    state = started.data["state"]
    assert state["status"] == "pending_approval", {"answer": started.message,
        "plan_errors": {key: (state["active_entities"].get("task_plan") or {}).get(key)
                        for key in ("planner_error", "rejected_step_ids", "domain_plan_repair")},
        "semantic": state["active_entities"].get("semantic_verifications"),
        "completed": [(row["step_id"], row["status"], row.get("result_message")) for row in state["completed_steps"]]}
    assert state["active_domain"] == parent_domain
    assert [step["tool_names"] for step in state["completed_steps"]] == [["workflows.save.prepare"]]
    assert "workflows.save.prepare" in prompts[0]
    pending = state["pending_actions"][0]
    assert pending["action_type"] == "ai.action_save_workflow_spec"
    assert pending["arguments"]["payload"]["proposal"]["spec"] == WORKFLOW_ACCEPTANCE_SPEC
    assert pending["semantic_verification"]["required"] is True
    assert state["active_entities"]["execution_budget"]["started_steps"] == 1
    assert not state["active_entities"].get("child_task_reservations")
    assert not workflow_store.workflow_store_path().exists()


def test_shared_configuration_discovery_does_not_authorize_writes_or_unrelated_business_domains():
    from AI.processors.tools import available_tools
    registry = available_tools()
    goal = workflow_save_prompt()
    candidates = task_runtime._planner_operation_candidates("orders", goal, limit=64)
    prepare = registry["workflows.save.prepare"]
    assert candidates[prepare.name].domain == prepare.domain == "workflows"
    assert task_runtime._direct_operation_domain_allowed("orders", prepare, goal)
    assert not task_runtime._direct_operation_allowed_for_goal(prepare.name, prepare, goal,
        authorization_context={"mode": "inspect", "intent_kind": "data_read"})
    stock_write = next(tool for tool in registry.values() if tool.domain == "stock"
        and tool.requires_approval and tool.action_type != "read")
    assert not task_runtime._direct_operation_domain_allowed("orders", stock_write, goal)
    assert stock_write.name not in candidates


def test_delegation_catalog_also_exposes_private_artifact_import_without_granting_access():
    from AI.processors.tools import available_tools
    registry = available_tools()
    candidates = task_runtime._planner_operation_candidates("general", "Run independent research", limit=20)
    assert {'operations.discover', 'agent.delegate', 'artifacts.read'}.issubset(candidates)
    assert len(candidates) <= 20
    import_result = registry['artifacts.read'].handler(artifact_id='not-granted', session_id='test-current',
        authorized_capabilities={})
    assert not import_result.success


@pytest.mark.parametrize("mode,intent", [("act", "action"), ("correct", "correction"), ("act", "approval_control")])
@pytest.mark.parametrize("owner", ["general", "stock"])
def test_general_action_with_quoted_future_export_does_not_become_orders(mode, intent, owner):
    message = "Bu kurallar paketinin taslağını onaya hazırla: «Bu listeyi Excel'e aktar». İçindeki işi şimdi çalıştırma."
    payload = {"mode": mode, "domain": owner, "intent_kind": intent,
        "objective": "Prepare only the current rules package", "request_shape": "action",
        "information_source": "unspecified", "operation_policy": "allow_new_operations",
        "requested_fields": ["action_result"], "requires_clarification": False, "clarification": ""}
    assert task_runtime._goal_has_report_export_intent(message)
    assert task_runtime._contextual_reference_requested(message)
    result = task_runtime.interpret_agent_turn(message, planner_client=lambda _: json.dumps(payload))
    assert result.success, result.message
    assert result.data["domain"] == owner
    expected_intent = "action" if mode == "act" and intent == "approval_control" else intent
    assert result.data["mode"] == mode and result.data["intent_kind"] == expected_intent
    assert result.data["objective"] == payload["objective"]
    assert result.data["requested_fields"] == ["action_result"]


def test_existing_orders_export_compatibility_still_repairs_stale_read_classification():
    message = "Bu doğrulanmış listeyi Excel'e hazırla; dosya üretmeden önce açık onayımı bekle."
    stale = {"mode": "inspect", "domain": "orders", "objective": "List pending returns",
        "intent_kind": "data_read", "requested_fields": ["claim_id", "status"],
        "requires_clarification": False, "clarification": ""}
    result = task_runtime.interpret_agent_turn(message, planner_client=lambda _: json.dumps(stale))
    assert result.success, result.message
    assert result.data["mode"] == "act" and result.data["domain"] == "orders"
    assert result.data["intent_kind"] == "action"
    assert result.data["requested_fields"] == ["artifact", "action_result"]
    assert "explicit_contextual_report_export_mode_to_act" in result.data["semantic_corrections"]
