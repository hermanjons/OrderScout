"""Saved attachment workflows use fresh reads of only current picker grants."""
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import patch

import pytest

from AI.processors import file_workspace, observation_artifacts, task_runtime, tools, workflow_store
from AI.processors.session_state import AgentSessionState, AgentTaskStep


def _spec(bound=True):
    return {"schema_version": 1, "name": "Dosya incelemesi",
            "instructions": "Seçili dosyayı yeniden oku; mevcut kaynaktan bir özet hazırla.",
            "objective_template": "{{attachment_id}} ek dosyasını incele." if bound else "Yeni kaynakları incele.",
            "parameter_schema": {"type": "object", "additionalProperties": False,
                "properties": {"attachment_id": {"type": "string", "scope": "attachment_id"}} if bound else {},
                "required": ["attachment_id"] if bound else []},
            "source_policy": {"description": "Her çalıştırmada seçili dosyayı yeniden oku.", "requires_current_sources": True},
            "effect_policy": {"description": "Her dosya oluşturmayı güncel onaya sun.", "requires_current_approval": True}}


@pytest.fixture
def picker_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(file_workspace, "ATTACHMENTS_ROOT", tmp_path / "imports")
    monkeypatch.setattr(observation_artifacts, "OBSERVATION_ARTIFACTS_ROOT", tmp_path / "observations")
    previous = AgentSessionState(goal="Previous file work", active_domain="general")
    metadata = []
    for index in range(2):
        file = tmp_path / f"chosen-{index}.json"
        file.write_text(json.dumps([{"sku": f"SKU-{index}", "revenue": 12.5, "currency": "TRY"}]), encoding="utf-8")
        metadata.append(file_workspace.register_attachment(file, previous.session_id))
    previous.active_entities["file_workspace"] = {"session_id": previous.session_id, "attachments": metadata}
    previous.active_entities["observation_artifacts"] = {"capabilities": [{"capability_token": "old-private-grant"}]}
    previous.active_entities["execution_budget"] = {"used_steps": 99}
    previous.completed_steps.append(AgentTaskStep(index=1, step_id="old", prompt="Old observation", status="completed",
                                                 verification_status="observed", tool_names=["files.read"], result_data={"tool_result": {"rows": []}}))
    previous.last_tool_results.append({"tool_names": ["files.read"], "data": {"rows": []}})
    return previous, metadata


def _invocation(tmp_path, previous, metadata):
    revision = workflow_store.save_prepared_workflow(workflow_store.prepare_workflow_save(_spec(), workflow_id="chosen-file-review"), root=tmp_path / "workflows")
    return workflow_store.prepare_workflow_invocation(
        revision.workflow_id, parameters={"attachment_id": metadata[0]["attachment_id"]}, current_session=previous,
        allowed_scope_bindings={"attachment_id": [row["attachment_id"] for row in metadata]}, root=tmp_path / "workflows",
    )


def test_actual_registered_attachment_is_read_again_by_fresh_model_planned_workflow(picker_workspace, tmp_path):
    previous, metadata = picker_workspace
    original = deepcopy(previous.to_dict())
    invocation = _invocation(tmp_path, previous, metadata)
    fresh = AgentSessionState.from_dict(invocation["session_state"])
    assert fresh.session_id != previous.session_id
    assert fresh.active_entities["file_workspace"] == {"session_id": previous.session_id, "attachments": [metadata[0]]}
    assert "observation_artifacts" not in fresh.active_entities and "execution_budget" not in fresh.active_entities
    assert fresh.completed_steps == fresh.last_tool_results == fresh.pending_actions == fresh.action_history == []
    assert previous.to_dict() == original
    assert fresh.active_entities["workflow_invocation"]["requires_current_sources"] is True
    plan = {"steps": [{"id": "fresh_read", "operation_id": "files.read", "arguments": {"attachment_id": metadata[0]["attachment_id"]},
                       "depends_on": [], "objective": "Read the current selected source", "expected_evidence": ["rows", "source_hash"]}]}
    def planner(prompt):
        if prompt.startswith("GoalPlan observation"):
            return json.dumps({"decision": "complete", "reason": "The source was actually read"})
        return json.dumps(plan)
    calls = []
    registry = tools.available_tools()
    actual = registry["files.read"]
    registry["files.read"] = replace(actual, handler=lambda **kwargs: calls.append(kwargs) or actual.handler(**kwargs))
    with patch("AI.processors.tools.available_tools", return_value=registry):
        result = task_runtime.run_agent_task(
            invocation["goal"], domain="general", session_state=fresh, planner_client=planner, persist=False,
            turn_interpretation={"mode": "inspect", "domain": "general", "intent_kind": "data_read", "valid": True,
                                 "requested_fields": ["records"], "requires_clarification": False},
        )
    assert result.success, result.message
    assert len(calls) == 1 and calls[0]["session_id"] == previous.session_id
    assert calls[0]["attachment_id"] == metadata[0]["attachment_id"]
    completed = result.data["state"]["completed_steps"]
    assert len(completed) == 1 and completed[0]["tool_names"] == ["files.read"]
    assert completed[0]["result_data"]["tool_result"]["rows"] == [{"sku": "SKU-0", "revenue": 12.5, "currency": "TRY"}]
    assert metadata[1]["attachment_id"] not in json.dumps(result.data["state"]["active_entities"]["file_workspace"])


@pytest.mark.parametrize("mutation", ["foreign_owner", "changed_hash", "ungranted", "unsupported_metadata"])
def test_workflow_attachment_binding_cannot_forge_current_picker_grants(picker_workspace, tmp_path, mutation):
    previous, metadata = picker_workspace
    if mutation == "foreign_owner":
        previous.active_entities["file_workspace"]["session_id"] = "different-owner"
    elif mutation == "changed_hash":
        previous.active_entities["file_workspace"]["attachments"][0]["sha256"] = "0" * 64
    elif mutation == "ungranted":
        previous.active_entities["file_workspace"]["attachments"] = [metadata[1]]
    else:
        previous.active_entities["file_workspace"]["attachments"][0]["approval_token"] = "forged"
    with pytest.raises(workflow_store.WorkflowValidationError):
        _invocation(tmp_path, previous, metadata)


def test_workflow_without_attachment_scope_does_not_inherit_file_workspace(picker_workspace, tmp_path):
    previous, _ = picker_workspace
    revision = workflow_store.save_prepared_workflow(workflow_store.prepare_workflow_save(_spec(False), workflow_id="unbound-review"), root=tmp_path)
    invocation = workflow_store.prepare_workflow_invocation(revision.workflow_id, parameters={}, current_session=previous, root=tmp_path)
    assert "file_workspace" not in invocation["session_state"]["active_entities"]


def test_workflow_attachment_binding_never_inherits_pending_approval(picker_workspace, tmp_path):
    previous, metadata = picker_workspace
    previous.pending_actions.append({"action_id": "old-action", "approval_token": "not-authority"})
    with pytest.raises(workflow_store.WorkflowValidationError, match="pending action"):
        _invocation(tmp_path, previous, metadata)
