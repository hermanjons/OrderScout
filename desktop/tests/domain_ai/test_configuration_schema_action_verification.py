"""Exact requested configuration constraints survive prepare and approval."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from AI.processors import semantic_verifier as verifier, tools, workflow_store
from AI.processors.business_acceptance_fixtures import WORKFLOW_ACCEPTANCE_SPEC
from AI.processors.session_state import AgentSessionState, AgentTaskStep, GoalPlan, PendingActionSnapshot
from AI.processors.task_runtime import run_agent_task
from AI.processors.turn_service import run_typed_control_turn


def _captured():
    return json.loads((Path(__file__).parent / "fixtures" /
                       "schedule_glm_schema_constraint_drift.json").read_text(encoding="utf-8"))


def test_prepare_review_receives_actual_argument_values_without_credentials_or_report_rows():
    state, step, tool = _state({'quantity': 99, 'apiKey': 'NEVER-SEND-CREDENTIAL',
        'report_snapshot': {'title': 'Native source report', 'source_domain': 'reports',
            'metadata': {'source_receipts': [{'operation_id': 'stock.inventory_overview'}]},
            'sheets': [{'name': 'Records', 'columns': [{'key': 'quantity', 'source_path': 'balance'}],
                       'rows': [['NEVER-SEND-ROW']]}]}}, goal='Prepare a quantity of 2 for approval.')
    def review(prompt):
        assert '"quantity": 99' in prompt
        assert '"source_path": "balance"' in prompt
        assert 'stock.inventory_overview' in prompt
        assert 'NEVER-SEND-CREDENTIAL' not in prompt and 'NEVER-SEND-ROW' not in prompt
        return json.dumps({'verdict': 'deny', 'objective_aligned': False, 'domain_aligned': True,
                           'unwanted_effect': False, 'reason': 'Actual quantity differs from the current user request'})
    result = verifier.verify_plan_step_semantics(state, step, tool, verifier_client=review)
    assert not result.success
    assert 'semantic_objective_operation_mismatch' in str(result.data)


def _verdict(schema, quote, *, path="/spec/parameter_schema", verdict="allow"):
    return {"verdict": verdict, "objective_aligned": verdict == "allow", "domain_aligned": True,
            "unwanted_effect": False, "reason": "Compare the exact current request and actual validation constraints",
            "configuration_schema_reviews": [{"argument_path": path, "requested_schema_json": json.dumps(schema),
                                               "requirement_quotes": [quote]}]}


def _state(arguments, *, goal="Create a configuration with required text caption, at most 80 characters.", name="config.preview"):
    def not_executed(**arguments):
        raise AssertionError("The semantic contract check must never execute an operation")
    step = AgentTaskStep(index=1, step_id="config", prompt=goal, objective=goal,
                         operation_candidates=[name], operation_domain="general", arguments=deepcopy(arguments))
    state = AgentSessionState(goal=goal, active_domain="general", status="running")
    state.active_entities["turn_interpretation"] = {"mode": "act", "domain": "general", "intent_kind": "action"}
    state.add_goal_plan(GoalPlan(goal=goal, domain="general", steps=[step], source="llm_direct"))
    tool = tools.AgentTool(name=name, domain="general", description="Prepare the requested configuration for approval",
                           parameters={"type": "object", "properties": {}}, handler=not_executed,
                           requires_approval=True, action_type="prepare")
    return state, step, tool


def test_actual_glm_blanket_allow_cannot_stamp_added_minimum_or_write_anything(tmp_path, monkeypatch):
    captured = _captured()
    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", tmp_path / "catalog")
    prompts = []
    def model(prompt):
        prompts.append(prompt)
        return json.dumps(captured["initial_semantic_verdict"] if prompt.startswith("OrderScout semantic action verifier")
                          else {"steps": []} if "basarisiz oldugu icin yeniden planla" in prompt
                          else captured["initial_plan"], ensure_ascii=False)
    result = run_agent_task(captured["prompt"], domain="general", planner_client=model, persist=False,
                            turn_interpretation=captured["initial_interpretation"],
                            db_name=str(tmp_path / "business.sqlite3"), max_replans=0)
    state = result.data["state"]
    assert state["status"] == "failed" and not state["pending_actions"]
    assert not workflow_store.workflow_store_path().exists()
    row = next(row for row in state["active_entities"]["semantic_verifications"] if row["phase"] == "plan_step")
    assert row["allowed"] is False and row["reason_codes"] == ["configuration_schema_review_missing"]
    assert state["completed_steps"][0]["tool_names"] == []
    assert any('"minLength": 1' in prompt and 'requested_schema_json' in prompt for prompt in prompts)


def test_actual_schema_drift_replans_corrected_new_proposal_and_exact_sqlite_readback(tmp_path, monkeypatch):
    captured = _captured()
    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", tmp_path / "catalog")
    initial = deepcopy(captured["initial_plan"])
    corrected = {"steps": [{"id": "corrected_configuration", "operation_id": "workflows.save.prepare",
        "arguments": {"spec": deepcopy(WORKFLOW_ACCEPTANCE_SPEC), "workflow_id": "correct-stock-review"},
        "depends_on": [], "objective": "Prepare only the exact requested current instruction package",
        "expected_evidence": ["action", "spec_hash"]}]}
    checks = []
    requests = []
    class Model:
        def reserve_task_budget(self, **budget):
            requests.append(budget)
        def __call__(self, prompt):
            if prompt.startswith("OrderScout semantic action verifier"):
                checks.append(prompt)
                return json.dumps(_verdict(WORKFLOW_ACCEPTANCE_SPEC["parameter_schema"],
                    "Tek parametre report_title olsun: zorunlu metin, en fazla 80 karakter. Başka parametre kabul etme.",
                    verdict="deny" if len(checks) == 1 else "allow"), ensure_ascii=False)
            if "basarisiz oldugu icin yeniden planla" in prompt:
                assert 'configuration_schema_request_mismatch' in prompt
                assert '"minLength": 1' in prompt
                return json.dumps(corrected, ensure_ascii=False)
            return json.dumps(initial, ensure_ascii=False)
    result = run_agent_task(captured["prompt"], domain="general", planner_client=Model(), persist=False,
                            turn_interpretation=captured["initial_interpretation"],
                            db_name=str(tmp_path / "business.sqlite3"), max_steps=4, max_replans=1)
    state = result.data["state"]
    assert state["status"] == "pending_approval", state["active_entities"].get("task_plan")
    assert [(step["step_id"], step["status"]) for step in state["completed_steps"]] == [
        ("step_1", "failed"), ("corrected_configuration", "completed")]
    assert state["active_entities"]["execution_budget"]["started_steps"] == 2
    assert state["active_entities"]["execution_budget"]["applied_replans"] == 1
    assert len(checks) == 2 and requests == [{"max_steps": 4}]
    original = state["completed_steps"][0]["arguments"]
    assert original["spec"]["parameter_schema"]["properties"]["report_title"]["minLength"] == 1
    pending = state["pending_actions"][0]
    assert pending["arguments"]["payload"]["proposal"]["spec"] == WORKFLOW_ACCEPTANCE_SPEC
    assert pending["semantic_verification"]["configuration_schema_fingerprint"]
    assert not workflow_store.workflow_store_path().exists()
    approved = run_typed_control_turn("Onaylıyorum.", mode="approve", session_state=state, client=None,
        db_name=str(tmp_path / "business.sqlite3"), allow_approval_execute=True)
    assert approved.success, approved.message
    stored = tools.available_tools()["workflows.read"].handler(workflow_id="correct-stock-review")
    assert stored.success and stored.data["spec"] == WORKFLOW_ACCEPTANCE_SPEC
    assert approved.data["execute"]["verify"]["verified_by"] == "workflow_exact_revision_sqlite_readback"


@pytest.mark.parametrize("alteration", ["added_minimum", "dropped_maximum", "added_default", "changed_type", "added_property"])
def test_generic_configuration_schema_drift_cannot_be_allowed_by_blanket_verdict(alteration):
    expected = {"type": "object", "properties": {"caption": {"type": "string", "maxLength": 80}},
                "required": ["caption"], "additionalProperties": False}
    proposed = deepcopy(expected)
    if alteration == "added_minimum": proposed["properties"]["caption"]["minLength"] = 1
    elif alteration == "dropped_maximum": proposed["properties"]["caption"].pop("maxLength")
    elif alteration == "added_default": proposed["properties"]["caption"]["default"] = "Surprise"
    elif alteration == "changed_type": proposed["properties"]["caption"]["type"] = "integer"
    else: proposed["properties"]["extra"] = {"type": "boolean"}
    state, step, tool = _state({"configuration": {"validation": proposed}})
    result = verifier.verify_plan_step_semantics(state, step, tool,
        verifier_client=lambda _: json.dumps(_verdict(expected, state.goal, path="/configuration/validation")))
    assert not result.success
    assert result.data["argument_problems"] == ["configuration_schema_request_mismatch:/configuration/validation"]
    assert verifier.configuration_schema_rejection_repairable(state, step, result)
    assert step.arguments["configuration"]["validation"] == proposed
    changed = deepcopy(state)
    changed.goal += " different current request"
    assert not verifier.configuration_schema_rejection_repairable(changed, step, result)


@pytest.mark.parametrize("case", ["missing", "invented_quote", "empty_quote", "duplicate_row", "duplicate_json_key"])
def test_constraint_review_requires_current_request_provenance_and_exact_unique_schema(case):
    schema = {"type": "object", "properties": {"caption": {"type": "string", "maxLength": 80}}}
    state, step, tool = _state({"configuration": schema})
    response = _verdict(schema, state.goal, path="/configuration")
    if case == "missing": response.pop("configuration_schema_reviews")
    elif case == "invented_quote": response["configuration_schema_reviews"][0]["requirement_quotes"] = ["The user demanded nonempty text"]
    elif case == "empty_quote": response["configuration_schema_reviews"][0]["requirement_quotes"] = [""]
    elif case == "duplicate_row": response["configuration_schema_reviews"] *= 2
    else: response["configuration_schema_reviews"][0]["requested_schema_json"] = '{"type":"object","type":"string"}'
    result = verifier.verify_plan_step_semantics(state, step, tool, verifier_client=lambda _: json.dumps(response))
    assert not result.success and verifier.configuration_schema_rejection_repairable(state, step, result)


def test_explicitly_requested_minimum_is_preserved_and_non_schema_actions_keep_existing_contract():
    schema = {"type": "object", "properties": {"caption": {"type": "string", "minLength": 1, "maxLength": 80}}}
    state, step, tool = _state({"configuration": schema}, goal="Create a text caption between 1 and 80 characters.")
    calls = []
    def review(prompt):
        calls.append(prompt)
        return json.dumps(_verdict(schema, state.goal, path="/configuration"))
    result = verifier.verify_plan_step_semantics(state, step, tool, verifier_client=review)
    assert result.success and len(calls) == 1
    assert step.arguments["configuration"]["properties"]["caption"]["minLength"] == 1
    state, step, tool = _state({"caption": "One caption"})
    basic = {"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
             "unwanted_effect": False, "reason": "The user requested this current action"}
    assert verifier.verify_plan_step_semantics(state, step, tool, verifier_client=lambda _: json.dumps(basic)).success


def test_prepared_immutable_payload_must_match_independently_reviewed_schema(tmp_path, monkeypatch):
    captured = _captured()
    spec = deepcopy(WORKFLOW_ACCEPTANCE_SPEC)
    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", tmp_path)
    state, step, _ = _state({"spec": spec}, goal=captured["prompt"], name="workflows.save.prepare")
    step.operation_domain = "workflows"
    tool = tools.available_tools()["workflows.save.prepare"]
    reviewed = verifier.verify_plan_step_semantics(state, step, tool,
        verifier_client=lambda _: json.dumps(_verdict(spec["parameter_schema"], captured["prompt"][:950])))
    assert reviewed.success
    prepared = tool.handler(spec=spec)
    assert prepared.success
    action = prepared.data["action"]
    stamped = verifier.verify_prepared_action(state, step, action)
    assert stamped.success
    drifted_spec = deepcopy(spec)
    drifted_spec["parameter_schema"]["properties"]["report_title"]["minLength"] = 1
    changed = tool.handler(spec=drifted_spec).data["action"]
    denied = verifier.verify_prepared_action(state, step, changed)
    assert not denied.success and "configuration_schema_payload_mismatch" in denied.data["argument_problems"]
    assert verifier.configuration_schema_rejection_repairable(state, step, denied)
    changed = PendingActionSnapshot.refresh_identity(changed)
    changed["semantic_verification"] = deepcopy(stamped.data["action"]["semantic_verification"])
    preflight = verifier.verify_pending_action_pre_execute(state, changed, db_name=str(tmp_path / "business.sqlite3"))
    assert not preflight.success
    assert "semantic_configuration_schema_changed" in preflight.data["semantic_verification"]["reason_codes"]
    assert not workflow_store.workflow_store_path().exists()


def test_mixed_unsafe_verifier_failure_never_receives_schema_repair_authority():
    schema = {"type": "object", "properties": {"caption": {"type": "string"}}}
    state, step, tool = _state({"configuration": schema})
    unsafe = _verdict(schema, state.goal, path="/configuration", verdict="deny")
    unsafe["domain_aligned"] = False
    unsafe["configuration_schema_reviews"][0]["requirement_quotes"] = ["Not the user request"]
    result = verifier.verify_plan_step_semantics(state, step, tool, verifier_client=lambda _: json.dumps(unsafe))
    assert not result.success
    assert "semantic_objective_operation_mismatch" in result.data["argument_problems"]
    assert result.data["configuration_schema_review_repairable"] is False
    assert not verifier.configuration_schema_rejection_repairable(state, step, result)


def test_actual_completed_workflow_read_schema_binding_is_reviewed_without_rewriting_model_arguments(tmp_path, monkeypatch):
    captured = _captured()
    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", tmp_path / "catalog")
    created = workflow_store.prepare_workflow_save(deepcopy(WORKFLOW_ACCEPTANCE_SPEC), workflow_id="source-instructions")
    workflow_store.save_prepared_workflow(created)
    plan = {"steps": [
        {"id": "actual_saved_spec", "operation_id": "workflows.read", "depends_on": [],
         "arguments": {"workflow_id": "source-instructions"}, "expected_evidence": ["spec"]},
        {"id": "bound_configuration", "operation_id": "workflows.save.prepare", "depends_on": ["actual_saved_spec"],
         "arguments": {"spec": {"$from_step": "actual_saved_spec", "path": "tool_result.spec"},
                       "workflow_id": "copied-instructions"}, "expected_evidence": ["action"]}]}
    calls = []
    def model(prompt):
        if prompt.startswith("OrderScout semantic action verifier"):
            calls.append(prompt)
            assert '"maxLength": 80' in prompt
            return json.dumps(_verdict(WORKFLOW_ACCEPTANCE_SPEC["parameter_schema"],
                                      captured["prompt"][:950]), ensure_ascii=False)
        if prompt.startswith("GoalPlan observation"):
            return '{"decision":"continue","reason":"Use the exact actual saved source in the declared remaining prepare"}'
        return json.dumps(plan)
    goal = captured["prompt"] + " Önce source-instructions kimlikli kayıtlı iş yönergesinin tam güncel sürümünü oku; paketin metin ve parametrelerini bu kaynaktan al."
    result = run_agent_task(goal, domain="general", planner_client=model, persist=False,
                            turn_interpretation=captured["initial_interpretation"],
                            db_name=str(tmp_path / "business.sqlite3"), max_steps=8, max_replans=1)
    state = result.data["state"]
    assert state["status"] == "pending_approval", json.dumps(state["active_entities"], ensure_ascii=False)
    assert len(calls) == 1
    assert [step["tool_names"] for step in state["completed_steps"]] == [["workflows.read"], ["workflows.save.prepare"]]
    assert state["completed_steps"][1]["arguments"]["spec"] == {"$from_step": "actual_saved_spec", "path": "tool_result.spec"}
    assert state["pending_actions"][0]["arguments"]["payload"]["proposal"]["spec"] == WORKFLOW_ACCEPTANCE_SPEC
    row = next(row for row in state["active_entities"]["semantic_verifications"]
               if row["phase"] == "plan_step" and row["operation_id"] == "workflows.save.prepare")
    contract = row["evidence"]["config_schema_contract"]
    assert contract["evaluated_arguments_sha256"] != contract["model_arguments_sha256"]
