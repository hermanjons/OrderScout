from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import stat
from unittest.mock import patch

import pytest

from AI.processors import observation_artifacts as artifacts
from AI.processors.observation_projection import source_projection_hash
from AI.processors.session_state import AgentSessionState, AgentTaskStep, Observation
from AI.processors.tools import AgentTool, available_tools


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "isolated-observation-artifacts"
    monkeypatch.setattr(artifacts, "OBSERVATION_ARTIFACTS_ROOT", root)
    return root


def _never_execute(**_kwargs):
    raise AssertionError("Historical observation reads must not execute source tools")


def _registry():
    return {"sources.read": AgentTool(
        name="sources.read", domain="general", description="Authoritative isolated source",
        handler=_never_execute, parameters={"type": "object", "properties": {}},
        result_schema={"type": "object", "properties": {"rows": {"type": "array"}}},
    )}


def _add_step(state, operation_id, result, *, step_id="source", depends_on=(), arguments=None,
              bindings=None, domain="general", observed_at="2026-10-07T08:15:00+03:00"):
    observation = Observation.create(domain=domain, operation_name=operation_id, success=True,
                                     source=operation_id, observed_at=observed_at,
                                     facts={"context_kind": "read_scope"})
    state.observations.append(observation)
    step = AgentTaskStep(index=len(state.completed_steps) + 1, prompt="Observed source",
                         step_id=step_id, operation_domain=domain, depends_on=list(depends_on),
                         arguments=deepcopy(arguments or {}), status="completed", tool_names=[operation_id],
                         observation_ids=[observation.observation_id], verification_status="observed",
                         result_data={"mode": "tool", "tool_result": deepcopy(result),
                                      "dependency_bindings": dict(bindings or {})})
    state.completed_steps.append(step)
    state.last_tool_results.append({"step": step.index, "tool_names": [operation_id], "data": deepcopy(result)})
    return step


def _state():
    state = AgentSessionState(goal="Observe an isolated source", active_domain="general", session_id="original-task")
    _add_step(state, "sources.read", {"tool": "sources.read", "rows": [
        {"sku": "001", "quantity": 6, "unit": "adet", "price": 10.5, "currency": "TRY", "unknown": None, "enabled": False},
        {"sku": "002", "quantity": 4, "unit": "adet", "price": 9.0, "currency": "USD"},
    ], "period": "2026-10-07", "account_scopes": [{"api_account_id": 101, "environment": "stage"}],
        "data_coverage": {"status": "partial"}, "truncated": True})
    return state


def _read(state, ref):
    return artifacts.read_observation_artifact(artifact_id=ref["artifact_id"], session_id=state.session_id,
        authorized_capabilities=state.active_entities["observation_artifacts"]["capabilities"])


def _document_path(store: Path, ref):
    return store / ref["artifact_id"] / "observation.json"


def test_immutable_historical_result_retains_types_scope_origin_schema_and_time(store):
    state = _state()
    original = deepcopy(state.completed_steps[0].result_data["tool_result"])
    ref = artifacts.publish_completed_observation(state, "source", registry=_registry())
    assert ref["result_hash"] == source_projection_hash(original)
    assert ref["origin"] == {"task_id": "original-task", "step_id": "source", "operation_id": "sources.read"}
    assert ref["observed_at"] == "2026-10-07T08:15:00+03:00"
    assert ref["fresh_read"] is False and ref["historical_observation"] is True
    assert ref["scope"]["result_scope"]["period"] == "2026-10-07"
    assert ref["scope"]["result_scope"]["data_coverage"] == {"status": "partial"}
    assert ref["result_schema"]["properties"]["rows"]["type"] == "array"
    assert "capability_token" not in json.dumps(ref) and str(store) not in json.dumps(ref)
    assert artifacts.publish_completed_observation(state, "source", registry=_registry()) == ref
    restored = AgentSessionState.from_dict(state.to_dict())
    assert artifacts.observation_artifact_refs(restored) == [ref]
    state.completed_steps[0].result_data["tool_result"]["rows"][0]["quantity"] = 999
    observed = _read(restored, ref)
    assert observed.success and observed.data["result"] == original
    assert observed.data["freshness"] == "historical_snapshot" and observed.data["fresh_read"] is False
    assert observed.data["observed_at"] != observed.data["read_at"]
    assert observed.data["historical_source_receipts"][0]["result_hash"] == ref["result_hash"]
    assert "capability_token" not in json.dumps(observed.data)


def test_private_session_capability_requires_explicit_runtime_transfer(store):
    previous = _state()
    ref = artifacts.publish_completed_observation(previous, "source", registry=_registry())
    next_state = AgentSessionState(goal="Use prior observed source", session_id="next-task", active_domain="general")
    old_capability = previous.active_entities["observation_artifacts"]["capabilities"][0]
    for fake in ([], [ref], [old_capability], [{**old_capability, "session_id": next_state.session_id}]):
        denied = artifacts.read_observation_artifact(artifact_id=ref["artifact_id"], session_id=next_state.session_id,
                                                     authorized_capabilities=fake)
        assert not denied.success and "result" not in denied.data
    assert artifacts.transfer_observation_capabilities(previous, next_state) == [ref]
    assert _read(next_state, ref).success
    transferred = next_state.active_entities["observation_artifacts"]["capabilities"][0]
    assert transferred["capability_token"] != old_capability["capability_token"]
    assert artifacts.transfer_observation_capabilities(previous, next_state) == [ref]
    assert len(next_state.active_entities["observation_artifacts"]["capabilities"]) == 1
    assert next_state.completed_steps == [] and next_state.pending_actions == []
    assert next_state.last_tool_results == []


def test_child_artifact_binding_uses_the_completed_receipt_and_retains_private_authority(store):
    from AI.processors import task_runtime
    child = _state()
    ref = artifacts.publish_completed_observation(child, 'source', registry=_registry())
    parent = AgentSessionState(goal='Inspect the child observation', session_id='parent-task', active_domain='general')
    artifacts.transfer_observation_capabilities(child, parent)
    _add_step(parent, 'agent.delegate', {'tool': 'agent.delegate', 'artifact_refs': [ref],
              'child_task_id': child.session_id, 'child_status': 'complete'}, step_id='child')
    step = AgentTaskStep(index=2, prompt='Read the exact child result', step_id='inspect',
                        operation_candidates=['artifacts.read'], depends_on=['child'],
                        arguments={'artifact_id': {'$from_step': 'child',
                                                   'path': 'tool_result.artifact_refs[0].artifact_id'}})
    kwargs, problems, bindings = task_runtime._resolve_step_arguments(parent, step, available_tools()['artifacts.read'])
    assert not problems and kwargs['artifact_id'] == ref['artifact_id']
    assert bindings == {'artifact_id': 'child:tool_result.artifact_refs[0].artifact_id'}
    assert _read(parent, ref).data['result'] == child.completed_steps[0].result_data['tool_result']
    step.arguments = {'artifact_id': 'obs_' + '0' * 32}
    _, problems, _ = task_runtime._resolve_step_arguments(parent, step, available_tools()['artifacts.read'])
    assert 'arguments.artifact_id:binding_observation_artifact_not_authorized' in problems
    step.arguments = {'artifact_id': {'$from_step': 'child', 'path': 'tool_result.artifact_refs[0].artifact_id'}}
    step.depends_on = []
    _, problems, _ = task_runtime._resolve_step_arguments(parent, step, available_tools()['artifacts.read'])
    assert 'arguments.artifact_id:binding_source_not_completed_dependency' in problems


def test_placeholder_child_binding_is_rejected_in_the_initial_plan_before_delegation():
    from AI.processors import task_runtime
    registry = available_tools()
    goal = 'Inspect the child stock observation and prepare a report for approval.'
    specifications = [
        {'id': 'child', 'operation_id': 'agent.delegate', 'arguments': {'objective': 'Read current stock only'},
         'depends_on': [], 'expected_evidence': ['artifact_refs']},
        {'id': 'inspect', 'operation_id': 'artifacts.read',
         'arguments': {'artifact_id': '$from_step:child.artifact_refs[0].artifact_id'},
         'depends_on': ['child'], 'expected_evidence': ['result']},
    ]
    diagnostics = []
    accepted, rejected = task_runtime._validate_direct_plan_specs('stock', specifications, goal,
        allowed_operations=registry, max_steps=8, validation_diagnostics=diagnostics,
        authorization_context={'mode': 'act', 'domain': 'stock', 'requested_fields': ['artifact']})
    assert not accepted and 'inspect' in rejected
    assert 'step_output_binding_must_be_typed_object' in json.dumps(diagnostics)
    specifications[1]['arguments']['artifact_id'] = {
        '$from_step': 'child', 'path': 'tool_result.artifact_refs[0].artifact_id'}
    accepted, rejected = task_runtime._validate_direct_plan_specs('stock', specifications, goal,
        allowed_operations=registry, max_steps=8,
        authorization_context={'mode': 'act', 'domain': 'stock', 'requested_fields': ['artifact']})
    assert not rejected and len(accepted) == 2


@pytest.mark.parametrize("changed", ["token", "hash", "session", "id"])
def test_forged_or_drifted_private_capabilities_fail_closed(store, changed):
    state = _state()
    ref = artifacts.publish_completed_observation(state, "source", registry=_registry())
    capability = deepcopy(state.active_entities["observation_artifacts"]["capabilities"][0])
    field = {"token": "capability_token", "hash": "artifact_hash", "session": "session_id", "id": "artifact_id"}[changed]
    capability[field] = "0" * 64
    result = artifacts.read_observation_artifact(artifact_id=ref["artifact_id"], session_id=state.session_id,
                                                authorized_capabilities=[capability])
    assert not result.success and result.data["verified"] is False and "result" not in result.data


def _derived_state():
    from AI.processors.analysis_operations import calculate_observations
    state = _state()
    registry = _registry()
    registry["analysis.calculate"] = available_tools()["analysis.calculate"]
    sources = [{"source_id": "observed", "source_step_id": "source", "operation_id": "sources.read",
                "result": state.completed_steps[0].result_data["tool_result"]}]
    request = {"sources": [{**sources[0], "result": {"$from_step": "source", "path": "tool_result"}}],
               "calculations": [{"calculation_id": "maximum_quantity", "operator": "maximum",
                                  "operands": [{"source_id": "observed", "path": "rows.0.quantity"},
                                               {"source_id": "observed", "path": "rows.1.quantity"}]}]}
    result = calculate_observations(sources=sources, calculations=request["calculations"])
    assert result.success, result.data
    _add_step(state, "analysis.calculate", result.data, step_id="calculate", depends_on=["source"],
              arguments=request, bindings={"sources[0].result": "source:tool_result"}, domain="analysis")
    return state, registry


def test_completed_derived_result_stores_full_revalidatable_source_graph(store):
    state, registry = _derived_state()
    ref = artifacts.publish_completed_observation(state, "calculate", registry=registry)
    document = json.loads(_document_path(store, ref).read_text(encoding="utf-8"))
    assert [node["step_id"] for node in document["source_graph"]] == ["source", "calculate"]
    assert document["source_graph"][1]["source_bindings"] == [{
        "argument_path": "sources[0].result", "source_step_id": "source", "source_path": "tool_result",
        "value_hash": document["source_graph"][0]["result_hash"],
    }]
    result = _read(state, ref)
    assert result.success and result.data["result"]["verified_calculations"][0]["result_value"] == 6
    assert len(result.data["historical_source_receipts"]) == 2
    assert state.action_history == []


@pytest.mark.parametrize("change,reason", [
    ("literal", "literal_source_rejected"), ("partial_literal", "literal_source_rejected"),
    ("binding", "binding_receipt_mismatch"), ("receipt", "source_receipt_drift"),
    ("missing_dependency", "source_not_completed_dependency"), ("cycle", "source_cycle"),
])
def test_literal_or_unsafe_derived_provenance_cannot_be_published(store, change, reason):
    state, registry = _derived_state()
    derived = state.completed_steps[1]
    if change == "literal":
        derived.arguments["sources"][0]["result"] = deepcopy(state.completed_steps[0].result_data["tool_result"])
    elif change == "partial_literal":
        derived.arguments["sources"].append({"result": {"rows": [{"quantity": 999}]}})
    elif change == "binding":
        derived.result_data["dependency_bindings"] = {}
    elif change == "receipt":
        derived.result_data["tool_result"]["source_receipts"][0]["source_result_hash"] = "0" * 64
        state.last_tool_results[-1]["data"] = deepcopy(derived.result_data["tool_result"])
    elif change == "missing_dependency":
        derived.depends_on = []
    else:
        state.completed_steps[0].depends_on = ["calculate"]
    with pytest.raises(ValueError, match=reason):
        artifacts.publish_completed_observation(state, "calculate", registry=registry)
    assert "observation_artifacts" not in state.active_entities


@pytest.mark.parametrize("change,reason", [
    ("dict_state", "runtime_state_required"), ("failed", "completed_observation_required"),
    ("pending", "completed_observation_required"), ("unverified", "completed_observation_required"),
    ("unlinked", "runtime_observation_required"), ("observation_tamper", "runtime_observation_required"),
    ("cache_tamper", "runtime_result_receipt_required"), ("foreign_operation", "source_operation_mismatch"),
])
def test_only_trusted_completed_linked_observations_can_be_published(store, change, reason):
    state = _state()
    step = state.completed_steps[0]
    if change == "dict_state":
        state = state.to_dict()
    elif change in {"failed", "pending"}:
        step.status = change
    elif change == "unverified":
        step.verification_status = "pending"
    elif change == "unlinked":
        step.observation_ids = []
    elif change == "observation_tamper":
        state.observations[0].facts["tampered"] = True
    elif change == "cache_tamper":
        state.last_tool_results[0]["data"]["rows"][0]["quantity"] = 999
    else:
        step.result_data["tool_result"]["tool"] = "another.read"
    with pytest.raises(ValueError, match=reason):
        artifacts.publish_completed_observation(state, "source", registry=_registry())


@pytest.mark.parametrize("effect", ["prepare", "execute", "destructive", "non_read"])
def test_prepared_or_executed_effect_cannot_publish_approval_authority(store, effect):
    state = _state()
    registry = _registry()
    tool = registry["sources.read"]
    changed = {"prepare": {"requires_approval": True}, "execute": {"action_type": "execute", "read_only": False},
               "destructive": {"destructive": True}, "non_read": {"read_only": False}}[effect]
    registry[tool.name] = AgentTool(**{**tool.__dict__, **changed})
    state.completed_steps[0].verification_status = "verified"
    with pytest.raises(ValueError, match="readonly_source_required"):
        artifacts.publish_completed_observation(state, "source", registry=registry)


@pytest.mark.parametrize("payload", [
    {"pending_action": {"action_id": "old"}}, {"approved_action": {"action_id": "old"}},
    {"action": {"action_type": "write", "arguments": {}}}, {"nested": {"execute_enabled": False}},
    {"approval_required": True}, {"rows": [{"api_secret": "fixture-secret-never-print"}]},
])
def test_control_or_secret_payload_is_rejected_without_scrubbing_source(store, payload):
    state = _state()
    state.completed_steps[0].result_data["tool_result"].update(payload)
    state.last_tool_results[0]["data"] = deepcopy(state.completed_steps[0].result_data["tool_result"])
    with pytest.raises(ValueError, match="authority_rejected|secret_payload_rejected"):
        artifacts.publish_completed_observation(state, "source", registry=_registry())


@pytest.mark.parametrize("changed", ["result", "schema", "origin", "scope", "observation", "source_binding"])
def test_any_persisted_result_schema_origin_scope_or_graph_drift_is_rejected(store, changed):
    state, registry = _derived_state()
    ref = artifacts.publish_completed_observation(state, "calculate", registry=registry)
    path = _document_path(store, ref)
    document = json.loads(path.read_text(encoding="utf-8"))
    if changed == "result":
        document["source_graph"][0]["result"]["rows"][0]["quantity"] = 999
    elif changed == "schema":
        document["source_graph"][0]["result_schema"] = {"type": "string"}
    elif changed == "origin":
        document["origin"]["operation_id"] = "forged.read"
    elif changed == "scope":
        document["source_graph"][0]["scope"]["result_scope"]["period"] = "today"
    elif changed == "observation":
        document["source_graph"][0]["observations"][0]["observed_at"] = "2026-10-08T00:00:00+00:00"
    else:
        document["source_graph"][1]["source_bindings"][0]["value_hash"] = "0" * 64
    path.write_text(json.dumps(document), encoding="utf-8")
    result = _read(state, ref)
    assert not result.success and result.data["reason"] == "observation_artifact_hash_drift"
    assert "result" not in result.data


def test_completed_source_mutation_cannot_replace_or_republish_existing_artifact(store):
    state = _state()
    ref = artifacts.publish_completed_observation(state, "source", registry=_registry())
    original = _document_path(store, ref).read_bytes()
    state.completed_steps[0].result_data["tool_result"]["rows"][0]["quantity"] = 999
    state.last_tool_results[0]["data"] = deepcopy(state.completed_steps[0].result_data["tool_result"])
    with pytest.raises(ValueError, match="completed_source_changed"):
        artifacts.publish_completed_observation(state, "source", registry=_registry())
    assert _document_path(store, ref).read_bytes() == original


def test_result_size_graph_and_structural_limits_fail_without_capabilities(store, monkeypatch):
    state = _state()
    monkeypatch.setattr(artifacts, "MAX_RESULT_BYTES", 20)
    with pytest.raises(ValueError, match="size_limit"):
        artifacts.publish_completed_observation(state, "source", registry=_registry())
    monkeypatch.setattr(artifacts, "MAX_RESULT_BYTES", 2 * 1024 * 1024)
    state, registry = _derived_state()
    monkeypatch.setattr(artifacts, "MAX_GRAPH_NODES", 1)
    with pytest.raises(ValueError, match="graph_limit"):
        artifacts.publish_completed_observation(state, "calculate", registry=registry)
    monkeypatch.setattr(artifacts, "MAX_JSON_DEPTH", 3)
    with pytest.raises(ValueError, match="structure_limit"):
        artifacts.publish_completed_observation(_state(), "source", registry=_registry())


@pytest.mark.parametrize("bad_id", ["../outside", "obs_" + "0" * 32 + "/..", "C:\\private", "", None])
def test_arbitrary_paths_are_never_accepted_as_artifact_ids(store, bad_id):
    result = artifacts.read_observation_artifact(artifact_id=bad_id, session_id="task", authorized_capabilities=[])
    assert not result.success and result.data["reason"] == "observation_artifact_invalid_id"


def test_windows_reparse_store_root_is_rejected_even_without_symlink_privilege(store, monkeypatch):
    store.mkdir()
    original_lstat = Path.lstat
    def marked(path, *args, **kwargs):
        result = original_lstat(path, *args, **kwargs)
        if path == store:
            from types import SimpleNamespace
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        return result
    monkeypatch.setattr(Path, "lstat", marked)
    with pytest.raises(ValueError, match="link_path_rejected"):
        artifacts.publish_completed_observation(_state(), "source", registry=_registry())


def test_unrelated_pending_action_is_not_copied_into_readonly_artifact(store):
    state = _state()
    state.pending_actions = [{"action_id": "unrelated", "execute_enabled": True}]
    state.status = "pending_approval"
    ref = artifacts.publish_completed_observation(state, "source", registry=_registry())
    result = _read(state, ref)
    assert result.success and "unrelated" not in json.dumps(result.data)
    next_state = AgentSessionState(goal="Only prior data", session_id="later-task")
    artifacts.transfer_observation_capabilities(state, next_state)
    assert next_state.pending_actions == [] and next_state.action_history == []


def test_actual_task_runtime_completed_file_read_can_publish_and_transfer_historical_data(store, tmp_path, monkeypatch):
    from AI.processors import file_workspace
    from AI.processors.task_runtime import run_agent_task
    monkeypatch.setattr(file_workspace, "ATTACHMENTS_ROOT", tmp_path / "attachments")
    selected = tmp_path / "selected.json"
    rows = [{"sku": "A", "quantity": 6, "unit": "adet", "unknown": None}]
    selected.write_text(json.dumps(rows), encoding="utf-8")
    previous = AgentSessionState(goal="Selected source", active_domain="general")
    attachment = file_workspace.register_attachment(selected, previous.session_id)
    previous.active_entities["file_workspace"] = {"session_id": previous.session_id, "attachments": [attachment]}
    registry = {name: tool for name, tool in available_tools().items() if name in {"files.read", "operations.discover"}}
    plan = {"steps": [{"id": "read_selected", "operation_id": "files.read",
                       "arguments": {"attachment_id": attachment["attachment_id"]}, "depends_on": [],
                       "objective": "Read the user selected file", "expected_evidence": ["rows", "source_hash"]}]}
    def planner(prompt):
        if prompt.startswith("GoalPlan observation"):
            return json.dumps({"decision": "complete", "reason": "The requested source rows are observed"})
        return json.dumps(plan)
    with patch("AI.processors.tools.available_tools", return_value=registry):
        result = run_agent_task("Read my selected JSON file and show the observed rows", domain="general",
                                session_state=previous, planner_client=planner, persist=False,
                                turn_interpretation={"mode": "act", "domain": "general", "intent_kind": "action",
                                                     "valid": True, "requested_fields": ["rows"],
                                                     "objective": "Read selected source rows", "requires_clarification": False})
    assert result.success, result.message
    state = AgentSessionState.from_dict(result.data["state"])
    assert state.completed_steps[0].verification_status == "observed"
    ref = artifacts.publish_completed_observation(state, "read_selected", registry=registry)
    selected.unlink()
    next_state = AgentSessionState(goal="Reuse that historical result", active_domain="general")
    artifacts.transfer_observation_capabilities(state, next_state)
    observed = _read(next_state, ref)
    assert observed.success and observed.data["result"]["rows"] == rows
    assert observed.data["fresh_read"] is False
    assert observed.data["artifact"]["origin"]["operation_id"] == "files.read"
    assert next_state.completed_steps == [] and next_state.active_entities.get("file_workspace") is None


def _historical_read_state(store):
    previous, registry = _derived_state()
    ref = artifacts.publish_completed_observation(previous, "calculate", registry=registry)
    current = AgentSessionState(goal="Reuse the previous calculation", active_domain="general", session_id="reuse-task")
    artifacts.transfer_observation_capabilities(previous, current)
    result = _read(current, ref)
    assert result.success
    registry["artifacts.read"] = AgentTool(name="artifacts.read", domain="general", description="Historical source",
                                           parameters=artifacts.OBSERVATION_ARTIFACT_READ_PARAMETERS,
                                           result_schema=artifacts.OBSERVATION_ARTIFACT_READ_OUTPUT_SCHEMA,
                                           handler=_never_execute)
    _add_step(current, "artifacts.read", result.data, step_id="historical_read",
              arguments={"artifact_id": ref["artifact_id"]}, observed_at="2026-10-08T09:30:00+03:00")
    return previous, current, ref, registry


def test_republishing_historical_read_preserves_original_time_and_full_cross_task_source_graph(store):
    previous, current, original_ref, registry = _historical_read_state(store)
    ref = artifacts.publish_completed_observation(current, "historical_read", registry=registry)
    assert ref["observed_at"] == original_ref["observed_at"] == "2026-10-07T08:15:00+03:00"
    document = json.loads(_document_path(store, ref).read_text(encoding="utf-8"))
    imported = document["source_graph"][0]["imported_artifacts"][0]
    assert imported["artifact_id"] == original_ref["artifact_id"]
    assert imported["artifact_hash"] == original_ref["artifact_hash"]
    assert [node["step_id"] for node in imported["document"]["source_graph"]] == ["source", "calculate"]
    # The new immutable artifact carries the original graph itself; retirement
    # of the prior task/file must not silently sever provenance or re-run it.
    _document_path(store, original_ref).unlink()
    final_state = AgentSessionState(goal="Read preserved evidence", session_id="final-task")
    artifacts.transfer_observation_capabilities(current, final_state, artifact_ids=[ref["artifact_id"]])
    observed = _read(final_state, ref)
    assert observed.success and observed.data["observed_at"] == original_ref["observed_at"]
    assert observed.data["result"]["result"]["verified_calculations"][0]["result_value"] == 6
    assert observed.data["content_is_untrusted_data"] is True
    assert final_state.completed_steps == []


@pytest.mark.parametrize("changed", ["value", "freshness", "timestamp", "scope", "missing_capability"])
def test_forged_historical_source_cannot_be_republished_as_new_observation(store, changed):
    previous, current, ref, registry = _historical_read_state(store)
    result = current.completed_steps[0].result_data["tool_result"]
    if changed == "value":
        result["result"]["verified_calculations"][0]["result_value"] = 999
    elif changed == "freshness":
        result["fresh_read"] = True
    elif changed == "timestamp":
        result["observed_at"] = "2026-10-08T09:30:00+03:00"
    elif changed == "scope":
        result["scope"]["domain"] = "foreign"
    else:
        current.active_entities["observation_artifacts"]["capabilities"] = []
    current.last_tool_results[0]["data"] = deepcopy(result)
    with pytest.raises(ValueError, match="historical_source_drift|not_authorized"):
        artifacts.publish_completed_observation(current, "historical_read", registry=registry)


def test_explicit_subset_transfer_cannot_grant_an_unknown_artifact(store):
    state = _state()
    ref = artifacts.publish_completed_observation(state, "source", registry=_registry())
    target = AgentSessionState(goal="Use only explicitly selected prior observations", session_id="subset-task")
    with pytest.raises(ValueError, match="not_authorized"):
        artifacts.transfer_observation_capabilities(state, target, artifact_ids=["obs_" + "0" * 32])
    assert "observation_artifacts" not in target.active_entities
    assert artifacts.transfer_observation_capabilities(state, target, artifact_ids=[]) == []
    assert not _read(target, ref).success
