"""Original durable bytes survive cleanup under real Windows current-user DPAPI.

Only model replies are scripted. Canonical SQLite tools, task checkpoints,
child reservation, scheduler, and encryption run without substitutes.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

import pytest

from AI.processors import task_store, workflow_store
from AI.processors.business_acceptance_fixtures import WORKFLOW_ACCEPTANCE_SPEC, seed_business_fixture
from AI.processors.business_agent_acceptance_cli import (
    ObservedCloudClient, _source_snapshot, retain_child_task_checkpoints,
    retain_scheduled_task_checkpoint, secret_safe,
)
from AI.processors.scheduled_task_runtime import run_scheduled_task
from AI.processors.session_state import ActiveScope, AgentSessionState
from AI.processors.workflow_scheduler import WorkflowScheduler
from Core.processors import credential_store
from tests.domain_ai.test_child_task_runtime import Model, _delegate, _read, _run
from tests.domain_ai.test_scheduled_task_runtime import ScriptedClient


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Original checkpoint retention uses Windows DPAPI")


def _decrypt(row, artifact):
    ciphertext = (artifact.parent / row["artifact_relative_path"]).read_bytes()
    original = credential_store._unprotect(ciphertext).encode("utf-8")
    assert hashlib.sha256(ciphertext).hexdigest() == row["ciphertext_sha256"]
    assert hashlib.sha256(original).hexdigest() == row["original_sha256"]
    assert len(ciphertext) == row["ciphertext_byte_count"]
    assert len(original) == row["original_byte_count"]
    return original


def _tokens(value):
    if isinstance(value, dict):
        found = [item for key, item in value.items() if key == "capability_token"]
        return found + [token for item in value.values() for token in _tokens(item)]
    if isinstance(value, list):
        return [token for item in value for token in _tokens(item)]
    return []


def _child_run(isolated, artifact, *, before=None):
    database, tasks = isolated / "business.sqlite3", isolated / "tasks"
    seed_business_fixture(str(database), isolation_root=isolated)
    state = AgentSessionState(goal="Only primary account", active_domain="general")
    state.set_active_scope(ActiveScope.create(domain="orders", account_ids=[101], environments=["stage"]))
    plan = {"steps": [_delegate(steps=2, replans=1),
        {"id": "parent_import", "operation_id": "artifacts.read", "depends_on": ["delegated"],
         "arguments": {"artifact_id": {"$from_step": "delegated", "path": "tool_result.artifact_refs[0].artifact_id"}},
         "expected_evidence": ["result", "artifact"]}]}
    selected = Model(plan, _read())
    selected.model_name = "fixture-model"
    before_records, ledger = [], []
    def retain_before(child_id, parent_id):
        originals = {role: (tasks / (task_id + ".json")).read_bytes()
                     for role, task_id in (("parent", parent_id), ("child", child_id))}
        manifest = retain_child_task_checkpoints(child_id, parent_id, stage="before_first_child_model",
            isolation_root=isolated, artifact_path=artifact, task_store_root=tasks)
        # The observer is called before the selected model receives any child prompt.
        assert not [row for row in selected.prompts if row[0]]
        for file in manifest["files"]:
            assert _decrypt(file, artifact) == originals[file["role"]]
        before_records.append(manifest)
        return before(child_id, parent_id) if before else manifest
    client = ObservedCloudClient(selected, ledger.append, before_child_callback=retain_before)
    result = _run(database, client, previous=state, persist=True, task_store_root=str(tasks))
    parent = result.data["state"]
    reservation = next(iter(parent["active_entities"]["child_task_reservations"].values()))
    return parent, reservation, before_records, ledger, selected


def test_real_child_initial_and_final_original_files_survive_cleanup_without_public_private_grants(tmp_path, monkeypatch):
    artifact = tmp_path / "evidence" / "campaign.json"
    store = tmp_path / "credential-store-must-stay-absent.json"
    monkeypatch.setenv(credential_store.CREDENTIAL_STORE_PATH_ENV, str(store))
    with tempfile.TemporaryDirectory(dir=tmp_path) as temporary:
        isolated = Path(temporary)
        parent, reservation, before, ledger, selected = _child_run(isolated, artifact)
        assert len(before) == 1
        initial = {row["role"]: json.loads(_decrypt(row, artifact)) for row in before[0]["files"]}
        child_id, parent_id = reservation["child_task_id"], parent["session_id"]
        assert initial["child"]["session_id"] == child_id != parent_id
        assert initial["child"]["active_entities"]["planning_not_started"] is True
        assert initial["child"]["active_entities"]["task_checkpoint"]["phase"] == "initialized"
        reserved = next(iter(initial["parent"]["active_entities"]["child_task_reservations"].values()))
        assert reserved["child_task_id"] == child_id and reserved["status"] == "running"
        assert initial["parent"]["active_entities"]["execution_budget"]["reserved_child_replans"] == 1
        original_graph = initial["parent"]["active_entities"]["task_checkpoint"]["inflight_step"]
        assert original_graph["step_id"] == "delegated" and original_graph["operation_candidates"] == ["agent.delegate"]
        assert any(row.get("durable_checkpoint_retention") == before[0] for row in ledger)
        assert selected.reservations == [{"max_steps": 8}]
        assert len([row for row in selected.prompts if row[0]]) >= 2
        # Preserve CRLF and surrounding JSON whitespace from the actual source file.
        child_path = isolated / "tasks" / (child_id + ".json")
        child_path.write_bytes(b" \r\n" + child_path.read_bytes() + b"\t \r\n")
        exact = {role: (isolated / "tasks" / (task_id + ".json")).read_bytes()
                 for role, task_id in (("parent", parent_id), ("child", child_id))}
        final = retain_child_task_checkpoints(child_id, parent_id, stage="after_child_oracle",
            isolation_root=isolated, artifact_path=artifact, task_store_root=isolated / "tasks")
        repeated = retain_child_task_checkpoints(child_id, parent_id, stage="after_child_oracle",
            isolation_root=isolated, artifact_path=artifact, task_store_root=isolated / "tasks")
        assert repeated["files"] == final["files"]  # A second capture cannot invalidate the earlier ciphertext hash.
        child = json.loads(exact["child"])
        assert child["status"] == "complete" and not child["remaining_steps"] and not child["pending_actions"]
        stock = child["completed_steps"][0]["result_data"]["tool_result"]
        assert {row["currency"]: row["amount"] for row in stock["stock_value_by_currency"]} == {"TRY": 400, "USD": 30}
        assert child["active_entities"]["child_delegation_policy"] == reserved["scope_policy"]
        grants = _tokens(child) + _tokens(json.loads(exact["parent"]))
        assert grants  # Real capability tokens exist in the original private checkpoints.
        public = json.dumps(secret_safe({"initial": before, "final": final}, ()))
        assert "capability_token" not in public
        for file in final["files"]:
            assert _decrypt(file, artifact) == exact[file["role"]]
        for manifest in [before[0], final]:
            for file in manifest["files"]:
                assert not Path(file["source_relative_path"]).is_absolute()
                assert not Path(file["artifact_relative_path"]).is_absolute()
                ciphertext = (artifact.parent / file["artifact_relative_path"]).read_bytes()
                assert all(token.encode("utf-8") not in ciphertext and token not in public for token in grants)
        source_root = isolated
    assert not source_root.exists()
    for file in final["files"]:
        assert _decrypt(file, artifact) == exact[file["role"]]
    assert not store.exists()
    assert all(path.suffix == ".dpapi" for path in (artifact.parent / "campaign-checkpoints").iterdir())


@pytest.fixture
def checkpoints(tmp_path):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    artifact = tmp_path / "retained" / "campaign.json"
    parent, reservation, _, _, _ = _child_run(isolated, artifact)
    return isolated, artifact, parent, reservation


@pytest.mark.parametrize("mutation", ["uuid", "escape", "id_mismatch", "malformed", "utf8", "nonobject",
                                    "outside_root", "parent_link", "scope", "budget", "same_id"])
def test_checkpoint_retention_rejects_wrong_identity_or_nonisolated_original_before_encryption(checkpoints, mutation):
    isolated, artifact, parent, reservation = checkpoints
    child_id, parent_id, root = reservation["child_task_id"], parent["session_id"], isolated / "tasks"
    path = root / (child_id + ".json")
    payload = json.loads(path.read_bytes())
    if mutation == "uuid": child_id = "q" * 32
    elif mutation == "escape": child_id = "../outside"
    elif mutation == "same_id": child_id = parent_id
    elif mutation == "outside_root": root = isolated.parent / "outside"
    elif mutation == "malformed": path.write_bytes(b"{not JSON}")
    elif mutation == "utf8": path.write_bytes(b"\xff\xfe")
    elif mutation == "nonobject": path.write_bytes(b"[]")
    else:
        if mutation == "id_mismatch": payload["session_id"] = uuid4().hex
        elif mutation == "parent_link": payload["active_entities"]["child_delegation_policy"]["parent_task_id"] = uuid4().hex
        elif mutation == "scope": payload["active_entities"]["child_delegation_policy"]["account_ids"] = {"orders": ["102"]}
        else: payload["active_entities"]["execution_budget"]["max_steps"] += 1
        path.write_text(json.dumps(payload), encoding="utf-8")
    existing = {p.name: p.read_bytes() for p in (artifact.parent / "campaign-checkpoints").iterdir()}
    with pytest.raises((ValueError, OSError, TypeError)):
        retain_child_task_checkpoints(child_id, parent_id, stage="after_child_oracle",
            isolation_root=isolated, artifact_path=artifact, task_store_root=root)
    assert {p.name: p.read_bytes() for p in (artifact.parent / "campaign-checkpoints").iterdir()} == existing


def test_dpapi_failure_or_bad_roundtrip_never_writes_plaintext_fallback(checkpoints, monkeypatch):
    isolated, artifact, parent, reservation = checkpoints
    target = artifact.parent / "unavailable.json"
    def unavailable(_):
        raise credential_store.CredentialStoreUnavailable("Unavailable in the test")
    monkeypatch.setattr(credential_store, "_protect", unavailable)
    with pytest.raises(credential_store.CredentialStoreUnavailable):
        retain_child_task_checkpoints(reservation["child_task_id"], parent["session_id"], stage="after_child_oracle",
            isolation_root=isolated, artifact_path=target, task_store_root=isolated / "tasks")
    assert not (target.parent / "unavailable-checkpoints").exists()
    monkeypatch.undo()
    monkeypatch.setattr(credential_store, "_unprotect", lambda _: "changed original bytes")
    with pytest.raises(ValueError, match="original checkpoint bytes"):
        retain_child_task_checkpoints(reservation["child_task_id"], parent["session_id"], stage="after_child_oracle",
            isolation_root=isolated, artifact_path=target, task_store_root=isolated / "tasks")
    assert not (target.parent / "unavailable-checkpoints").exists()


def test_pre_child_retention_failure_prevents_real_selected_provider_callback(tmp_path):
    isolated, artifact = tmp_path / "isolated", tmp_path / "retained" / "campaign.json"
    isolated.mkdir()
    def reject(child_id, parent_id):
        raise ValueError("The pre-provider evidence could not be retained")
    parent, reservation, before, ledger, selected = _child_run(isolated, artifact, before=reject)
    assert before and reservation["status"] == "needs_clarification"
    assert not [row for row in selected.prompts if row[0]]
    assert parent["status"] != "complete"
    assert any(row.get("delegated_child") and row["response_received"] is False for row in ledger)


@pytest.mark.parametrize("case", ["temporary_destination", "already_observed_initial", "stage_escape"])
def test_retention_stage_and_persistent_destination_fail_closed(checkpoints, case):
    isolated, artifact, parent, reservation = checkpoints
    stage = "after_child_oracle"
    if case == "temporary_destination": artifact = isolated / "output" / "campaign.json"
    elif case == "already_observed_initial": stage = "before_first_child_model"
    else: stage = "../unknown"
    with pytest.raises(ValueError):
        retain_child_task_checkpoints(reservation["child_task_id"], parent["session_id"], stage=stage,
            isolation_root=isolated, artifact_path=artifact, task_store_root=isolated / "tasks")
    assert not (isolated / "output").exists()


def test_real_scheduled_initial_and_final_checkpoint_bytes_and_fenced_metadata(tmp_path, monkeypatch):
    isolated, artifact = tmp_path / "isolated", tmp_path / "evidence" / "schedule.json"
    isolated.mkdir()
    database, tasks, workflows = isolated / "business.sqlite3", isolated / "tasks", isolated / "workflows"
    seed_business_fixture(str(database), isolation_root=isolated)
    monkeypatch.setattr(task_store, "TASK_STORE_DIR", tasks)
    revision = workflow_store.save_prepared_workflow(workflow_store.prepare_workflow_save(
        deepcopy(WORKFLOW_ACCEPTANCE_SPEC), workflow_id="retained-schedule"), root=workflows)
    scheduler = WorkflowScheduler(root=isolated / "schedules", workflow_root=workflows)
    proposal = scheduler.prepare_schedule_save(revision.workflow_id, revision_id=revision.revision_id,
        parameters={"report_title": "Exact scheduled stock"}, interval_seconds=3600,
        first_due_at=datetime.now(timezone.utc), allowed_scope_bindings={}, budget={"max_steps": 8, "max_replans": 1})
    scheduler.save_prepared_schedule(proposal, confirmed_action_hash=proposal["action_hash"], approved_by="human")
    lease = scheduler.claim_due(owner_id="retention-test")[0]
    initial, original_bytes = [], {}
    attach = scheduler.attach_task_session
    def capture(lease, session_id):
        attach(lease, session_id)
        original_bytes["initial"] = (tasks / (session_id + ".json")).read_bytes()
        initial.append(retain_scheduled_task_checkpoint(scheduler, lease.run_id, session_id,
            stage="scheduled_task_attached", isolation_root=isolated, artifact_path=artifact))
    monkeypatch.setattr(scheduler, "attach_task_session", capture)
    client = ScriptedClient(scheduler, tasks, "Exact scheduled stock", isolated / "stock.xlsx")
    result = run_scheduled_task(lease, scheduler=scheduler, client=client, provider_code="openrouter",
        model_name=client.model_name, db_name=str(database), allowed_scope_bindings={},
        current_session=AgentSessionState(goal="Previous task", status="complete"))
    assert result.success, result.message
    run = result.data["run"]
    original_bytes["final"] = (tasks / (run["session_id"] + ".json")).read_bytes()
    final = retain_scheduled_task_checkpoint(scheduler, run["run_id"], run["session_id"],
        stage="scheduled_task_observed", isolation_root=isolated, artifact_path=artifact)
    assert _decrypt(initial[0]["checkpoint"], artifact) == original_bytes["initial"]
    assert _decrypt(final["checkpoint"], artifact) == original_bytes["final"]
    started, ended = json.loads(original_bytes["initial"]), json.loads(original_bytes["final"])
    assert started["active_entities"]["task_checkpoint"]["phase"] == "initialized"
    assert started["active_entities"]["planning_not_started"] is True
    assert started["session_id"] == ended["session_id"] != run["receipt"]["submission_session_id"]
    assert ended["status"] == "pending_approval" and len(ended["pending_actions"]) == 1
    assert ended["active_entities"]["execution_budget"]["started_steps"] == 3
    for manifest in (initial[0], final):
        metadata = manifest["run_lease_evidence"]
        assert metadata["owner_id"] == "retention-test" and metadata["attempts"] == 1
        assert metadata["execution_started_at"] and metadata["lease_expires_at"]
        assert metadata["session_id"] == run["session_id"]
        assert "lease_token" not in metadata
        assert lease.lease_token not in json.dumps(manifest)
    assert initial[0]["run_lease_evidence"]["status"] == "running"
    assert final["run_lease_evidence"]["status"] == "awaiting_approval"
    assert client.bound_before_plan == [run["session_id"]] and not client.output.exists()
    with pytest.raises(ValueError, match="durable run binding"):
        retain_scheduled_task_checkpoint(scheduler, run["run_id"], uuid4().hex,
            stage="scheduled_task_observed", isolation_root=isolated, artifact_path=artifact)
    with pytest.raises(ValueError, match="preceded neither"):
        retain_scheduled_task_checkpoint(scheduler, run["run_id"], run["session_id"],
            stage="scheduled_task_attached", isolation_root=isolated, artifact_path=artifact)


def test_checkpoint_retention_dependencies_and_test_are_in_actual_source_fingerprint():
    snapshot = _source_snapshot()
    assert snapshot["missing_requested_sources"] == []
    assert {"Core/processors/credential_store.py", "tests/domain_ai/test_business_child_checkpoint_retention.py"} <= {
        row["path"] for row in snapshot["files"]}
