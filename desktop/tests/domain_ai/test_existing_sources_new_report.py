"""The user's report follow-up must retain source limits without disabling preparation."""
from copy import deepcopy
import json

import pytest

from AI.processors import task_runtime, tools
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.processors.source_policy import (
    ALLOW_FRESH, EXISTING_ONLY, source_access_context, state_source_policy,
)
from AI.processors.task_store import save_agent_task_state, load_agent_task_state


def action():
    return {"mode": "act", "domain": "general", "intent_kind": "action", "request_shape": "artifact_report",
            "objective": "Prepare Excel from the previous verified observations", "requested_fields": ["artifact"],
            "information_source": "local_business_data", "operation_policy": "allow_new_operations",
            "source_policy": EXISTING_ONLY, "requires_clarification": False, "clarification": ""}


def test_actual_logged_contradiction_gets_one_model_repair_instead_of_an_observation_answer():
    # Actual 16 Oct source log: act/action + existing_observations_only. No new
    # tool ran. Captured enum decision is replayed, never presented as live AI.
    rejected = {**action(), "request_shape": "action", "operation_policy": "existing_observations_only"}
    rejected.pop("source_policy")
    calls = []
    def model(prompt):
        calls.append(prompt)
        if len(calls) > 1:
            assert "artifact_source_operation_policy_conflict" in prompt
            assert "bana bu bilgilerden bir excel oluştur hele" in prompt
        return json.dumps(rejected if len(calls) == 1 else action())
    result = task_runtime.interpret_agent_turn("bana bu bilgilerden bir excel oluştur hele", planner_client=model)
    assert result.success, result.data
    assert len(calls) == 2
    assert result.data["mode"] == "act" and result.data["request_shape"] == "artifact_report"
    assert result.data["operation_policy"] == "allow_new_operations"
    assert result.data["source_policy"] == EXISTING_ONLY
    assert result.data["turn_interpretation_repair"]["applied"]


def test_repeated_inconsistent_interpretation_fails_after_one_repair():
    candidate = {**action(), "operation_policy": "existing_observations_only"}
    calls = []
    result = task_runtime.interpret_agent_turn("Create Excel from previous results",
        planner_client=lambda prompt: calls.append(prompt) or json.dumps(candidate))
    assert not result.success and len(calls) == 2


def test_correcting_an_existing_explanation_is_not_a_new_report_action_conflict():
    payload = {**action(), "mode": "correct", "intent_kind": "correction", "request_shape": "record_detail",
               "operation_policy": "existing_observations_only", "requested_fields": ["artifact"]}
    calls = []
    result = task_runtime.interpret_agent_turn("Önceki raporun açıklamasını düzelt. Yeni işlem yapma.",
        planner_client=lambda prompt: calls.append(prompt) or json.dumps(payload))
    assert result.success, result.data
    assert len(calls) == 1 and result.data["operation_policy"] == "existing_observations_only"


def test_model_repair_cannot_turn_missing_old_source_evidence_into_new_reads():
    rejected = {**action(), "operation_policy": "existing_observations_only"}
    responses = iter([rejected, {**action(), "source_policy": ALLOW_FRESH}])
    result = task_runtime.interpret_agent_turn("Create Excel from the previous observations",
        planner_client=lambda _: json.dumps(next(responses)))
    assert not result.success
    assert result.data["turn_interpretation_repair"]["repair_error"] == "interpretation_repair_source_policy_widening"


@pytest.mark.parametrize("message", [
    "Önceki doğrulanmış verilerden Excel hazırla. Yeni sorgu çalıştırma, dosyayı henüz kaydetme.",
    "Yalnızca önceki verileri kullanarak Excel oluştur.",
])
def test_source_only_wording_keeps_model_authorized_report_preparation(message):
    result = task_runtime.interpret_agent_turn(message, planner_client=lambda _: json.dumps(action()))
    assert result.success and result.data["mode"] == "act", result.data
    assert result.data["source_policy"] == EXISTING_ONLY
    assert result.data["operation_policy"] == "allow_new_operations"


def test_blanket_no_tools_boundary_is_still_preserved():
    result = task_runtime.interpret_agent_turn("Hiçbir araç kullanma, yeni işlem yapma. Önceki raporu açıkla.",
        planner_client=lambda _: json.dumps(action()))
    assert result.success and result.data["operation_policy"] == "existing_observations_only"
    assert result.data["mode"] not in {"act", "correct"}


def test_catalog_and_nested_tasks_cannot_turn_discovery_into_fresh_source_authority():
    original = tools.available_tools()
    assert "orders.summary" in original and "agent.delegate" in original
    with source_access_context(EXISTING_ONLY):
        allowed = tools.available_tools()
        assert {"artifacts.read", "operations.discover", "reports.build_snapshot", "reports.xlsx.prepare"} <= allowed.keys()
        assert not {"orders.summary", "web.search", "web.open", "files.read", "agent.delegate"} & allowed.keys()
        with source_access_context(ALLOW_FRESH):
            assert tools.available_tools().keys() == allowed.keys()
    assert tools.available_tools().keys() == original.keys()


@pytest.mark.parametrize("operation_id", ["orders.summary", "stock.inventory_overview", "web.search", "files.read", "agent.delegate"])
def test_plan_argument_and_dispatch_boundaries_reject_fresh_reads_even_with_full_registry(operation_id):
    registry = tools.available_tools()
    tool = registry[operation_id]
    spec = {"id": "fresh", "operation_id": operation_id, "arguments": {}, "depends_on": [],
            "objective": "Read replacement source", "expected_evidence": []}
    diagnostics = []
    specs, rejected = task_runtime._validate_direct_plan_specs("general", [spec], "Create Excel", allowed_operations=registry,
        max_steps=8, authorization_context=action(), validation_diagnostics=diagnostics)
    assert not specs and rejected
    assert "source_policy:fresh_source_or_effect_not_authorized" in diagnostics[0]["reason_codes"]
    state = AgentSessionState(goal="Create Excel", active_domain="general")
    state.active_entities["source_access_policy"] = {"version": 1, "source_policy": EXISTING_ONLY}
    # A replan/model cannot broaden a persisted native policy by changing its
    # interpretation or by introducing an otherwise valid source operation.
    state.active_entities["turn_interpretation"] = {**action(), "source_policy": ALLOW_FRESH}
    step = AgentTaskStep(index=1, prompt="Read replacement source", step_id="fresh",
                         operation_candidates=[operation_id], operation_domain=tool.domain)
    _, problems, _ = task_runtime._resolve_step_arguments(state, step, tool)
    assert "source_policy:fresh_source_or_effect_not_authorized" in problems
    result = task_runtime._run_bound_domain_read_step(state, step, db_name="unused.sqlite3")
    assert not result.success
    assert result.data["argument_problems"] == ["source_policy:fresh_source_or_effect_not_authorized"]


def test_pause_checkpoint_keeps_native_source_authority(tmp_path):
    state = AgentSessionState(goal="Previous source report", active_domain="general", status="paused")
    state.active_entities["source_access_policy"] = {"version": 1, "source_policy": EXISTING_ONLY}
    state.active_entities["turn_interpretation"] = deepcopy(action())
    save_agent_task_state(state, root=tmp_path)
    restored = load_agent_task_state(state.session_id, root=tmp_path)
    assert state_source_policy(restored) == EXISTING_ONLY
    restored.active_entities["turn_interpretation"]["source_policy"] = ALLOW_FRESH
    assert state_source_policy(restored) == EXISTING_ONLY


def test_new_conversation_reply_replaces_previous_task_response_receipt():
    state = AgentSessionState(goal="Previous failed projection", active_domain="general", status="complete")
    state.active_entities["response_synthesis"] = {"final_projection_verified": False,
                                                 "final_source": "deterministic_projection_failed"}
    result = task_runtime.run_model_conversation_turn("Teşekkürler", objective="Acknowledge the user", mode="chat",
        chat_client=lambda _: "Rica ederim.", session_state=state)
    assert result.success
    assert result.data["state"]["active_entities"]["response_synthesis"] == result.data["response_synthesis"]
    assert result.data["state"]["active_entities"]["final_answer"] == result.data["answer"]


def test_report_reference_is_visible_even_when_model_allows_fresh_sources():
    from AI.processors.turn_evidence import existing_source_reference_context
    state = AgentSessionState(goal="Create Excel from those details", active_domain="general")
    state.active_entities["turn_interpretation"] = {**action(), "source_policy": ALLOW_FRESH}
    state.record_turn(role="assistant", content="Total units 952; first five 926; share 97.27%.")
    context = existing_source_reference_context(state)
    assert "952" in context["prior_answer"] and "97.27%" in context["prior_answer"]
    assert "explicit new scope takes precedence" in context["boundary"]
    assert context["available_granted_observations"] == []
