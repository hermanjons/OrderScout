from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from AI.processors import tools, workflow_store
from AI.processors.business_acceptance_fixtures import WORKFLOW_ACCEPTANCE_SPEC, workflow_save_prompt
from AI.processors.business_agent_acceptance_cli import (
    SCENARIOS, local_acceptance_approval_problems, retain_approved_workflow,
    secret_safe, validate_business_turn, workflow_fresh_source_problems, workflow_proposal_problems,
)
from AI.processors.operation_runtime import execute_approved_operation


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", tmp_path)
    result = tools.workflows_prepare_save(spec=deepcopy(WORKFLOW_ACCEPTANCE_SPEC), workflow_id="pilot-review")
    assert result.success, result.message
    return result.data["action"], tmp_path


def test_natural_save_prompt_contains_exact_human_instruction_and_parameter_constraints():
    text = workflow_save_prompt()
    assert WORKFLOW_ACCEPTANCE_SPEC["instructions"] in text
    assert WORKFLOW_ACCEPTANCE_SPEC["objective_template"] in text
    assert "80 karakter" in text and "Henüz kalıcı olarak kaydetme" in text
    assert SCENARIOS["workflow_run"]["workflow_invocation"] == {"report_title": "Pilot Tekrar Stok Raporu"}


def test_workflow_boundary_accepts_only_valid_exact_synthetic_catalog_proposal(prepared):
    action, root = prepared
    assert local_acceptance_approval_problems(action, root) == []
    assert workflow_proposal_problems(action) == []
    assert not workflow_store.workflow_store_path().exists()
    wrong = deepcopy(action)
    wrong["arguments"]["payload"]["extra_effect"] = {"execute_enabled": True}
    assert local_acceptance_approval_problems(wrong, root)
    assert local_acceptance_approval_problems(action, root / "different-sandbox")
    wrong = deepcopy(action)
    wrong["external_write"] = True
    assert "approval_has_external_or_destructive_effect" in local_acceptance_approval_problems(wrong, root)


@pytest.mark.parametrize("field", ["instructions", "objective_template"])
def test_regenerated_valid_proposal_cannot_change_the_human_contract(prepared, field):
    _, root = prepared
    changed = deepcopy(WORKFLOW_ACCEPTANCE_SPEC)
    changed[field] += " silently changed"
    action = tools.workflows_prepare_save(spec=changed).data["action"]
    assert "workflow_user_contract_changed:" + field in workflow_proposal_problems(action)


def test_regenerated_valid_parameter_contract_cannot_change_user_constraints(prepared):
    changed = deepcopy(WORKFLOW_ACCEPTANCE_SPEC)
    changed["parameter_schema"]["properties"]["report_title"]["maxLength"] = 800
    action = tools.workflows_prepare_save(spec=changed).data["action"]
    assert "workflow_parameter_constraints_changed" in workflow_proposal_problems(action)


def test_approved_workflow_retention_reopens_exact_head_and_keeps_only_recipe(prepared):
    action, root = prepared
    execution = execute_approved_operation(action, idempotency_key="acceptance-workflow", audit_path=root / "audit.jsonl")
    assert execution.success, execution.message
    turn = {"scenario_id": "workflow_save_approve", "approved_action": action,
            "execute": {"success": True, "message": execution.message, "data": execution.data}}
    retained = retain_approved_workflow(turn, isolation_root=root, artifact_path=root / "artifacts" / "live.json")
    saved_file = Path(retained["artifact_path"])
    saved = json.loads(saved_file.read_text(encoding="utf-8"))
    assert saved["spec"] == WORKFLOW_ACCEPTANCE_SPEC
    assert retained["sha256"] == hashlib.sha256(saved_file.read_bytes()).hexdigest()
    assert retained["spec_hash"] == workflow_store.read_workflow("pilot-review").spec.content_hash
    assert retained["saved_execution_authority"] is False
    assert not list(saved_file.parent.glob("*.sqlite3"))
    changed = deepcopy(turn)
    changed["execute"]["data"]["verify"]["spec_hash"] = "wrong"
    with pytest.raises(ValueError, match="identity"):
        retain_approved_workflow(changed, isolation_root=root, artifact_path=root / "bad.json")


def test_workflow_approval_acceptance_requires_current_exact_readback(prepared):
    action, root = prepared
    execution = execute_approved_operation(action, idempotency_key="acceptance-current", audit_path=root / "audit.jsonl")
    turn = {"success": True, "answer": "Saved", "execute": {"success": True, "data": execution.data}, "runtime": {}}
    assert validate_business_turn(turn, SCENARIOS["workflow_save_approve"], model="test/model") == []
    turn["execute"]["data"]["verify"]["current_head_matches_approved_revision"] = False
    assert "workflow_exact_current_revision_readback_missing" in validate_business_turn(
        turn, SCENARIOS["workflow_save_approve"], model="test/model")


def test_artifact_serialization_redacts_private_grant_without_mutating_live_state():
    live = {"active_entities": {"observation_artifacts": {"session_id": "session-a", "capabilities": [{
        "artifact_id": "observation-a", "content_hash": "public-hash", "origin": {"operation_id": "stock.inventory_overview"},
        "capability_token": "private-authority-token"}]}}}
    before = deepcopy(live)
    serialized = secret_safe(live, ())
    assert live == before
    assert "private-authority-token" not in json.dumps(serialized)
    grant = serialized["active_entities"]["observation_artifacts"]["capabilities"][0]
    assert grant["private_capability_redacted"] is True
    assert grant["artifact_id"] == "observation-a" and grant["content_hash"] == "public-hash"


def test_workflow_fresh_sources_cannot_pass_on_saved_instructions_or_historical_artifacts():
    turn = {"raw_turn_data": {"state": {"completed_steps": [], "active_entities": {"workflow_invocation": {
        "fresh_model_plan_required": True, "requires_current_sources": True, "requires_current_approval": True}}}}}
    assert workflow_fresh_source_problems(turn) == ["workflow_current_stock_read_missing"]
    turn["raw_turn_data"]["state"]["active_entities"]["workflow_invocation"]["requires_current_sources"] = False
    assert "workflow_fresh_invocation_authority_boundary_missing" in workflow_fresh_source_problems(turn)
