from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from AI.processors import workflow_store as workflows
from AI.processors.session_state import ActiveScope, AgentSessionState, AgentTaskStep


def _spec():
    return {"schema_version": 1, "name": "Mağaza incelemesi",
            "instructions": "  Güncel satışları stokla karşılaştır. Para birimlerini ayrı tut.  ",
            "objective_template": "{{environment}} ortamındaki {{account_id}} hesabının son {{days}} gününü incele; {{title}} raporunu hazırla.",
            "parameter_schema": {"type": "object", "additionalProperties": False, "required": ["account_id", "environment", "days", "title"],
                                 "properties": {"account_id": {"type": "integer", "minimum": 1, "scope": "account_id"},
                                                "environment": {"type": "string", "enum": ["stage", "production"], "scope": "environment"},
                                                "days": {"type": "integer", "minimum": 1, "maximum": 90},
                                                "title": {"type": "string", "maxLength": 80}}},
            "source_policy": {"description": "Güncel hesaptan yeniden oku; geçmiş sonuçları kaynak kabul etme.", "requires_current_sources": True},
            "effect_policy": {"description": "Her dosya oluşturma işlemi için o çalıştırmanın tam teklifini onaya sun.", "requires_current_approval": True}}


def _parameters():
    return {"account_id": 101, "environment": "stage", "days": 7, "title": "Haftalık görünüm"}


def _scopes():
    return {"account_id": [101], "environment": ["stage"]}


def _saved(root, spec=None):
    return workflows.save_prepared_workflow(workflows.prepare_workflow_save(spec or _spec(), workflow_id="weekly-research"), root=root)


def test_prepare_is_exact_reviewable_and_creates_no_catalog(tmp_path):
    payload = _spec()
    action = workflows.prepare_workflow_save(payload, workflow_id="weekly-research")
    assert action["spec"] == payload
    assert action["requires_current_approval"] is True
    assert action["spec_hash"] == workflows.WorkflowSpec.from_dict(payload).content_hash
    review = workflows.render_workflow_review(action["spec"])
    assert payload["instructions"] in review and payload["objective_template"] in review
    assert payload["source_policy"]["description"] in review and payload["effect_policy"]["description"] in review
    assert list(tmp_path.iterdir()) == []


def test_spec_and_revision_are_deeply_immutable_and_preserve_user_text(tmp_path):
    payload = _spec()
    spec = workflows.WorkflowSpec.from_dict(payload)
    original_hash = spec.content_hash
    payload["parameter_schema"]["properties"]["days"]["maximum"] = 10000
    returned = spec.to_dict()
    returned["instructions"] = "Changed"
    returned["parameter_schema"]["properties"]["days"]["maximum"] = 20000
    assert spec.to_dict() == _spec() and spec.content_hash == original_hash
    with pytest.raises(FrozenInstanceError):
        spec._canonical_json = "{}"
    revision = _saved(tmp_path, spec.to_dict())
    with pytest.raises(FrozenInstanceError):
        revision.revision_id = "changed"
    assert workflows.read_workflow("weekly-research", root=tmp_path).spec.to_dict() == _spec()


def test_revision_chain_cas_and_idempotent_old_proposal_never_rewind_current_head(tmp_path):
    original_action = workflows.prepare_workflow_save(_spec(), workflow_id="weekly-research")
    first = workflows.save_prepared_workflow(original_action, root=tmp_path)
    assert workflows.save_prepared_workflow(original_action, root=tmp_path) == first
    modified = _spec()
    modified["instructions"] += " Eksik veriyi açıkça belirt."
    second_action = workflows.prepare_workflow_save(modified, workflow_id=first.workflow_id, expected_revision_id=first.revision_id)
    second = workflows.save_prepared_workflow(second_action, root=tmp_path)
    assert second.parent_revision_id == first.revision_id and second.revision_id != first.revision_id
    assert workflows.read_workflow(first.workflow_id, revision_id=first.revision_id, root=tmp_path) == first
    assert workflows.save_prepared_workflow(original_action, root=tmp_path) == first
    assert workflows.read_workflow(first.workflow_id, root=tmp_path) == second
    assert workflows.list_workflow_revisions(first.workflow_id, root=tmp_path) == [first, second]
    stale = _spec()
    stale["name"] = "Stale update"
    with pytest.raises(workflows.WorkflowConflictError):
        workflows.save_prepared_workflow(workflows.prepare_workflow_save(stale, workflow_id=first.workflow_id,
                                                                        expected_revision_id=first.revision_id), root=tmp_path)
    assert workflows.list_workflows(root=tmp_path)[0]["revision_id"] == second.revision_id


def test_read_and_list_never_create_store_and_do_not_mutate_saved_rows(tmp_path):
    assert workflows.list_workflows(root=tmp_path) == []
    with pytest.raises(FileNotFoundError):
        workflows.read_workflow("weekly-research", root=tmp_path)
    assert list(tmp_path.iterdir()) == []
    first = _saved(tmp_path)
    database = workflows.workflow_store_path(root=tmp_path)
    before = database.read_bytes()
    for _ in range(3):
        assert workflows.read_workflow(first.workflow_id, root=tmp_path) == first
        assert len(workflows.list_workflows(root=tmp_path)) == 1
        assert workflows.list_workflow_revisions(first.workflow_id, root=tmp_path) == [first]
    assert database.read_bytes() == before


@pytest.mark.parametrize("field", ["pending_actions", "approval_token", "observations", "tool_result", "credentials", "step_graph", "source_path"])
def test_saved_spec_cannot_embed_previous_authority_or_execution_graph(field):
    value = _spec()
    value[field] = {"previous": "authority"}
    with pytest.raises(workflows.WorkflowValidationError):
        workflows.prepare_workflow_save(value)


@pytest.mark.parametrize("text", [r"Read C:\production\orders.sqlite3", "/home/user/source.csv", "../private/source.json",
                                 "private/source.csv", r"private\source.xlsx",
                                 "file:///private/source.xlsx", "api_key=previous-secret", "Bearer previous-token", "sk-123456789abcdefgh",
                                 '{"tool_result":{"count":999}}', "pending_action=old-token", "observations: prior-evidence"])
def test_instructions_and_parameter_enums_cannot_store_paths_or_credentials(text):
    value = _spec()
    value["instructions"] = text
    with pytest.raises(workflows.WorkflowValidationError):
        workflows.prepare_workflow_save(value)
    value = _spec()
    value["parameter_schema"]["properties"]["title"]["enum"] = [text]
    with pytest.raises(workflows.WorkflowValidationError):
        workflows.prepare_workflow_save(value)


@pytest.mark.parametrize("change", ["default", "source_path", "untyped_scope", "old_source_allowed", "no_current_approval", "object_payload"])
def test_schema_cannot_smuggle_defaults_source_authority_or_disable_current_gates(change):
    value = _spec()
    schema = value["parameter_schema"]
    if change == "default":
        schema["properties"]["account_id"]["default"] = 101
    elif change == "source_path":
        schema["properties"]["source_path"] = {"type": "string"}
    elif change == "untyped_scope":
        schema["properties"]["account_id"].pop("scope")
    elif change == "old_source_allowed":
        value["source_policy"]["requires_current_sources"] = False
    elif change == "no_current_approval":
        value["effect_policy"]["requires_current_approval"] = False
    else:
        schema["properties"]["historical_result"] = {"type": "object"}
    with pytest.raises(workflows.WorkflowValidationError):
        workflows.prepare_workflow_save(value)


@pytest.mark.parametrize("template", ["{{__class__}}", "{{days + 1}}", "{{days.__class__}}", "{{missing}}", "{{days", "{{__import__('os').system('anything')}}"])
def test_templates_cannot_evaluate_code_or_reference_undeclared_values(template):
    value = _spec()
    value["objective_template"] = template
    with pytest.raises(workflows.WorkflowValidationError):
        workflows.WorkflowSpec.from_dict(value)


def test_render_is_literal_one_pass_and_scope_binds_current_session_only():
    spec = workflows.WorkflowSpec.from_dict(_spec())
    params = _parameters()
    params["title"] = "{{days}} {literal}"
    rendered = workflows.render_workflow(spec, params, allowed_scope_bindings=_scopes())
    assert "{{days}} {literal} raporunu hazırla" in rendered
    assert spec.to_dict()["instructions"] in rendered
    with pytest.raises(workflows.WorkflowValidationError):
        workflows.render_workflow(spec, params)
    with pytest.raises(workflows.WorkflowValidationError):
        workflows.render_workflow(spec, params, allowed_scope_bindings={"account_id": [102], "environment": ["stage"]})


@pytest.mark.parametrize("field,value", [("account_id", True), ("days", "7"), ("days", 0), ("days", 91),
                                        ("environment", "production"), ("title", "x" * 81), ("title", r"C:\private\source.json")])
def test_typed_parameters_are_not_coerced_or_allowed_outside_current_scope(field, value):
    params = _parameters()
    params[field] = value
    with pytest.raises(workflows.WorkflowValidationError):
        workflows.render_workflow(workflows.WorkflowSpec.from_dict(_spec()), params, allowed_scope_bindings=_scopes())


def test_date_array_scope_and_native_numeric_types():
    value = _spec()
    value["objective_template"] = "{{day}} dosyalarını {{attachments}} oku; {{ratio}} oranını kullan."
    value["parameter_schema"] = {"type": "object", "additionalProperties": False, "required": ["day", "attachments", "ratio"],
                                 "properties": {"day": {"type": "string", "format": "date"},
                                                "attachments": {"type": "array", "items": {"type": "string"}, "scope": "attachment_id", "minItems": 1, "maxItems": 2},
                                                "ratio": {"type": "number", "minimum": 0, "maximum": 1}}}
    spec = workflows.WorkflowSpec.from_dict(value)
    params = {"day": "2026-10-08", "attachments": ["current-file-id"], "ratio": 0.25}
    assert "0.25" in workflows.render_workflow(spec, params, allowed_scope_bindings={"attachment_id": ["current-file-id"]})
    for bad in ({**params, "attachments": ["old-file-id"]}, {**params, "day": "2026-02-30"}, {**params, "ratio": float("nan")},
                {**params, "attachments": ["current-file-id"] * 3}):
        with pytest.raises(workflows.WorkflowValidationError):
            workflows.render_workflow(spec, bad, allowed_scope_bindings={"attachment_id": ["current-file-id"]})


@pytest.mark.parametrize("field,changed", [("spec_hash", "0" * 64), ("revision_id", "wfr_" + "0" * 64),
                                         ("requires_current_approval", False), ("action_id", "old-action-id"), ("expected_revision_id", "wfr_" + "0" * 64)])
def test_changed_proposal_is_rejected_before_creating_any_store(tmp_path, field, changed):
    action = workflows.prepare_workflow_save(_spec(), workflow_id="weekly-research")
    action[field] = changed
    with pytest.raises(workflows.WorkflowIntegrityError):
        workflows.save_prepared_workflow(action, root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_current_catalog_revision_cannot_be_updated_or_deleted_in_place(tmp_path):
    first = _saved(tmp_path)
    connection = sqlite3.connect(workflows.workflow_store_path(root=tmp_path))
    try:
        for sql in ("UPDATE workflow_revisions SET spec_json='{}'", "DELETE FROM workflow_revisions"):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql)
            connection.rollback()
    finally:
        connection.close()
    assert workflows.read_workflow(first.workflow_id, root=tmp_path) == first


def test_corrupted_revision_content_is_detected_even_when_database_identity_is_valid(tmp_path):
    first = _saved(tmp_path)
    with sqlite3.connect(workflows.workflow_store_path(root=tmp_path)) as connection:
        connection.execute("DROP TRIGGER immutable_revision_update")
        connection.execute("UPDATE workflow_revisions SET spec_hash=?", ("0" * 64,))
    with pytest.raises(workflows.WorkflowIntegrityError):
        workflows.read_workflow(first.workflow_id, root=tmp_path)


def test_foreign_or_future_catalog_is_not_modified(tmp_path):
    database = workflows.workflow_store_path(root=tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('preserve')")
    before = database.read_bytes()
    with pytest.raises(workflows.WorkflowIntegrityError):
        _saved(tmp_path)
    assert database.read_bytes() == before


@pytest.mark.parametrize("broken", ["missing_parent", "missing_head_revision", "changed_version", "wal_mode"])
def test_revision_chain_and_catalog_format_errors_are_not_silently_accepted(tmp_path, broken):
    first = _saved(tmp_path)
    second_spec = _spec()
    second_spec["name"] = "Second revision"
    second = workflows.save_prepared_workflow(workflows.prepare_workflow_save(second_spec, workflow_id=first.workflow_id,
                                                                            expected_revision_id=first.revision_id), root=tmp_path)
    connection = sqlite3.connect(workflows.workflow_store_path(root=tmp_path))
    try:
        if broken == "missing_parent":
            connection.execute("DROP TRIGGER immutable_revision_delete")
            connection.execute("DELETE FROM workflow_revisions WHERE revision_id=?", (first.revision_id,))
        elif broken == "missing_head_revision":
            connection.execute("UPDATE workflow_heads SET revision_id=?", ("wfr_" + "0" * 64,))
        elif broken == "changed_version":
            connection.execute("PRAGMA user_version=999")
        else:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.commit()
    finally:
        connection.close()
    if broken != "wal_mode":
        with pytest.raises(workflows.WorkflowIntegrityError):
            workflows.read_workflow(first.workflow_id, root=tmp_path)
        with pytest.raises(workflows.WorkflowIntegrityError):
            workflows.list_workflows(root=tmp_path)
    new_spec = _spec()
    new_spec["name"] = "Must not append to broken catalog"
    with pytest.raises(workflows.WorkflowIntegrityError):
        workflows.save_prepared_workflow(workflows.prepare_workflow_save(new_spec, workflow_id=first.workflow_id,
                                                                        expected_revision_id=second.revision_id), root=tmp_path)


def test_storage_uses_delete_journal_and_extra_sync_at_commit(tmp_path):
    observed = []
    original = workflows._insert_revision
    def insert(connection, revision):
        observed.append((connection.execute("PRAGMA journal_mode").fetchone()[0], connection.execute("PRAGMA synchronous").fetchone()[0]))
        original(connection, revision)
    with patch.object(workflows, "_insert_revision", side_effect=insert):
        _saved(tmp_path)
    assert observed == [("delete", 3)]


def test_empty_optional_text_is_preserved_but_scope_values_cannot_be_blank():
    value = _spec()
    value["parameter_schema"]["properties"]["note"] = {"type": "string", "minLength": 0}
    rendered = workflows.render_workflow(workflows.WorkflowSpec.from_dict(value), {**_parameters(), "note": ""}, allowed_scope_bindings=_scopes())
    assert '"note":""' in rendered


def test_concurrent_revision_proposals_have_exactly_one_winner(tmp_path):
    first = _saved(tmp_path)
    actions = []
    for title in ("Writer one", "Writer two"):
        value = _spec()
        value["name"] = title
        actions.append(workflows.prepare_workflow_save(value, workflow_id=first.workflow_id, expected_revision_id=first.revision_id))
    barrier = threading.Barrier(2, timeout=10)
    def commit(action):
        barrier.wait()
        try:
            return workflows.save_prepared_workflow(action, root=tmp_path)
        except workflows.WorkflowConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(commit, actions))
    assert results.count("conflict") == 1
    winner = next(result for result in results if result != "conflict")
    assert workflows.read_workflow(first.workflow_id, root=tmp_path) == winner
    assert len(workflows.list_workflow_revisions(first.workflow_id, root=tmp_path)) == 2


def test_separate_processes_cannot_overwrite_a_concurrent_revision(tmp_path):
    first = _saved(tmp_path)
    script = """import json, sys
from AI.processors import workflow_store as w
action=json.load(open(sys.argv[2], encoding='utf-8'))
print('ready', flush=True)
sys.stdin.readline()
try:
    result=w.save_prepared_workflow(action, root=sys.argv[1])
    print(result.revision_id, flush=True)
except w.WorkflowConflictError:
    print('conflict', flush=True)
"""
    processes = []
    try:
        for index in range(2):
            value = _spec()
            value["name"] = f"Process {index}"
            proposal = tmp_path / f"proposal-{index}.json"
            proposal.write_text(json.dumps(workflows.prepare_workflow_save(value, workflow_id=first.workflow_id,
                                                                          expected_revision_id=first.revision_id)), encoding="utf-8")
            process = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), str(proposal)],
                                       cwd=Path(__file__).resolve().parents[2], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            processes.append(process)
        for process in processes:
            assert process.stdout.readline().strip() == "ready"
        for process in processes:
            process.stdin.write("start\n")
            process.stdin.flush()
        outcomes = []
        for process in processes:
            output, error = process.communicate(timeout=20)
            assert process.returncode == 0, error
            outcomes.append(output.strip())
        assert outcomes.count("conflict") == 1
        assert workflows.read_workflow(first.workflow_id, root=tmp_path).revision_id == next(value for value in outcomes if value != "conflict")
        assert len(workflows.list_workflow_revisions(first.workflow_id, root=tmp_path)) == 2
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_actual_process_loss_between_revision_insert_and_head_update_keeps_previous_revision(tmp_path):
    first = _saved(tmp_path)
    changed = _spec()
    changed["name"] = "Uncommitted revision"
    action = workflows.prepare_workflow_save(changed, workflow_id=first.workflow_id, expected_revision_id=first.revision_id)
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps(action), encoding="utf-8")
    script = """import json, os, sys
from AI.processors import workflow_store as w
original = w._insert_revision
def interrupted(connection, revision):
    connection.execute('PRAGMA cache_size=1')
    connection.execute('PRAGMA cache_spill=ON')
    original(connection, revision)
    os._exit(29)
w._insert_revision = interrupted
w.save_prepared_workflow(json.load(open(sys.argv[2], encoding='utf-8')), root=sys.argv[1])
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(proposal_file)], cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 29, result.stderr
    assert workflows.read_workflow(first.workflow_id, root=tmp_path) == first
    assert workflows.list_workflow_revisions(first.workflow_id, root=tmp_path) == [first]
    second = workflows.save_prepared_workflow(action, root=tmp_path)
    assert workflows.read_workflow(first.workflow_id, root=tmp_path) == second


def test_run_submits_a_fresh_goal_with_current_clients_and_no_previous_authority(tmp_path):
    first = _saved(tmp_path)
    previous = AgentSessionState(goal="Old task", active_domain="general", status="complete")
    previous.completed_steps = [AgentTaskStep(index=1, step_id="old", prompt="Old canned graph", status="completed")]
    previous.remaining_steps = [AgentTaskStep(index=2, step_id="stale", prompt="Stale step")]
    previous.last_tool_results = [{"tool_result": {"count": 999}}]
    previous.action_history = [{"approved_by": "old-user", "approval_token": "previous-authority"}]
    previous.active_entities = {"execution_budget": {"started_steps": 99}, "observation_artifacts": {"secret_capability": "old"},
                                "file_workspace_session_id": "current-import-owner",
                                "runtime_context": {"source": "cloud", "provider_id": 1, "model_name": "current/model", "api_key": "must-drop"}}
    previous.active_scopes["orders"] = ActiveScope.create(domain="orders", account_ids=[102], environments=["production"],
                                                         filters={"period": "old_90_days", "source_snapshot": "old-snapshot"})
    before = previous.to_dict()
    planner = object()
    received = []
    def shared_runner(goal, **options):
        received.append((goal, options))
        return {"model_plan_requested": True, "state": options["session_state"]}
    result = workflows.run_workflow(first.workflow_id, parameters=_parameters(), runner=shared_runner, planner_client=planner,
                                    current_session=previous, allowed_scope_bindings=_scopes(), root=tmp_path,
                                    runner_options={"max_steps": 12, "domain": "general",
                                                    "runtime_context": {"source": "cloud", "provider_id": 2, "model_name": "fresh/model"}})
    assert result["model_plan_requested"] is True
    goal, options = received[0]
    state = options["session_state"]
    assert "101" in goal and "son 7 gününü" in goal
    assert options["planner_client"] is planner and options["max_steps"] == 12
    assert state["session_id"] != previous.session_id
    for field in ("completed_steps", "remaining_steps", "pending_actions", "observations", "last_tool_results", "action_history"):
        assert state[field] == []
    assert "execution_budget" not in state["active_entities"] and "observation_artifacts" not in state["active_entities"]
    assert state["active_entities"]["file_workspace_session_id"] == "current-import-owner"
    assert "api_key" not in state["active_entities"]["runtime_context"]
    assert state["active_entities"]["runtime_context"]["model_name"] == "fresh/model"
    assert state["active_scopes"]["orders"]["account_ids"] == ["101"]
    assert state["active_scopes"]["orders"]["environments"] == ["stage"]
    assert state["active_scopes"]["orders"]["filters"] == {}
    assert state["active_entities"]["workflow_invocation"]["requires_current_approval"] is True
    assert previous.to_dict() == before


def test_pending_authority_and_canned_or_approval_runner_options_never_reach_runner(tmp_path):
    first = _saved(tmp_path)
    calls = []
    def runner(*args, **kwargs):
        calls.append((args, kwargs))
    current = AgentSessionState(goal="Current task", pending_actions=[{"action_id": "current-action", "action_type": "write"}])
    with pytest.raises(workflows.WorkflowValidationError):
        workflows.run_workflow(first.workflow_id, parameters=_parameters(), runner=runner, planner_client=object(),
                                current_session=current, allowed_scope_bindings=_scopes(), root=tmp_path)
    for field in ("turn_interpretation", "step_graph", "approved_by", "action_id", "allow_approval_execute"):
        with pytest.raises(workflows.WorkflowValidationError):
            workflows.run_workflow(first.workflow_id, parameters=_parameters(), runner=runner, planner_client=object(),
                                    runner_options={field: "old-authority"}, allowed_scope_bindings=_scopes(), root=tmp_path)
    assert calls == []


def test_invocation_helper_reads_exact_revision_and_preserves_current_state_on_validation_failure(tmp_path):
    first = _saved(tmp_path)
    changed = _spec()
    changed["name"] = "New head"
    workflows.save_prepared_workflow(workflows.prepare_workflow_save(
        changed, workflow_id=first.workflow_id, expected_revision_id=first.revision_id), root=tmp_path)
    previous = AgentSessionState(goal="Existing UI task", status="complete")
    previous.last_tool_results = [{"secret": "old observation"}]
    previous.active_entities["file_workspace_session_id"] = "current-import-owner"
    before = previous.to_dict()
    invocation = workflows.prepare_workflow_invocation(
        first.workflow_id, parameters=_parameters(), current_session=previous,
        allowed_scope_bindings=_scopes(), revision_id=first.revision_id, root=tmp_path)
    assert invocation["revision"] == first
    assert invocation["session_state"]["goal"] == invocation["goal"]
    assert invocation["session_state"]["last_tool_results"] == []
    assert invocation["session_state"]["active_entities"]["file_workspace_session_id"] == "current-import-owner"
    for kwargs in ({"parameters": {"account_id": 999}}, {"revision_id": "wfr_" + "f" * 64}):
        arguments = {"parameters": _parameters(), "revision_id": first.revision_id, **kwargs}
        with pytest.raises((workflows.WorkflowValidationError, workflows.WorkflowIntegrityError, KeyError)):
            workflows.prepare_workflow_invocation(first.workflow_id, current_session=previous,
                allowed_scope_bindings=_scopes(), root=tmp_path, **arguments)
    assert previous.to_dict() == before


def test_public_web_reference_is_descriptive_and_old_runtime_metadata_is_not_reused(tmp_path):
    value = _spec()
    value["instructions"] = "Güncel bilgi için https://example.com/data/source.csv sayfasını oku."
    first = _saved(tmp_path, value)
    previous = AgentSessionState(goal="Previous model")
    previous.active_entities["runtime_context"] = {"source": "cloud", "model_name": "stale/model"}
    captured = []
    def runner(goal, **options):
        captured.append(options)
    workflows.run_workflow(first.workflow_id, parameters=_parameters(), runner=runner, planner_client=object(),
                           current_session=previous, allowed_scope_bindings=_scopes(), root=tmp_path)
    assert "runtime_context" not in captured[0]["session_state"]["active_entities"]
