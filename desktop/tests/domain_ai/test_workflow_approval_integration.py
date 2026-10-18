"""Exercise saved instructions through actual tools and shared effect control."""
from copy import deepcopy

import pytest

from AI.processors import tools, workflow_store
from AI.processors.operation_runtime import execute_approved_operation, verify_workflow_spec_save
from AI.processors.session_state import AgentSessionState
from AI.processors.turn_service import run_typed_control_turn


def _spec():
    return {"schema_version": 1, "name": "Stok incelemesi", "instructions": "Güncel stoku oku ve para birimlerini ayrı göster.",
            "objective_template": "Son {{days}} günü incele.", "parameter_schema": {
                "type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 31}},
                "required": ["days"], "additionalProperties": False},
            "source_policy": {"description": "Her çalışmada kaynakları yeniden oku.", "requires_current_sources": True},
            "effect_policy": {"description": "Dosya oluşturmayı o çalışmanın onayına sun.", "requires_current_approval": True}}


@pytest.fixture
def isolated_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", tmp_path)
    return tmp_path


def _prepared_state():
    result = tools.available_tools()["workflows.save.prepare"].handler(spec=_spec(), workflow_id="stock-review")
    assert result.success, result.message
    state = AgentSessionState(goal="Bu yönergeleri kaydet", active_domain="general", status="pending_approval")
    state.add_pending_action(result.data["action"])
    return result, state


def test_prepare_then_exact_shared_chat_approval_saves_and_independently_reads_current_revision(isolated_catalog):
    prepared, state = _prepared_state()
    assert not workflow_store.workflow_store_path().exists()
    result = run_typed_control_turn("Onaylıyorum.", mode="approve", session_state=state, client=None,
                                    db_name=str(isolated_catalog / "unrelated-business.sqlite3"), allow_approval_execute=True)
    assert result.success, result.message
    verify = result.data["execute"]["verify"]
    assert verify["verified"] is True
    assert verify["verified_by"] == "workflow_exact_revision_sqlite_readback"
    assert verify["current_head_matches_approved_revision"] is True
    read = tools.workflows_read(workflow_id=prepared.data["workflow_id"])
    assert read.success and read.data["spec"] == _spec()
    assert read.data["revision_id"] == verify["current_revision_id"] == prepared.data["revision_id"]
    assert result.data["state"]["pending_actions"] == []
    assert state.pending_actions  # The caller's input remains unchanged.


def test_cancel_and_disabled_approval_do_not_create_catalog(isolated_catalog):
    _, state = _prepared_state()
    blocked = run_typed_control_turn("Onaylıyorum.", mode="approve", session_state=state, client=None,
                                     db_name="unused", allow_approval_execute=False)
    assert blocked.data["mode"] == "approval_blocked"
    cancelled = run_typed_control_turn("Vazgeç", mode="cancel", session_state=state, client=None,
                                       db_name="unused", allow_approval_execute=True)
    assert cancelled.data["state"]["status"] == "cancelled"
    assert not workflow_store.workflow_store_path().exists()


def test_mutated_exact_proposal_is_rejected_before_effect(isolated_catalog):
    _, state = _prepared_state()
    state.pending_actions[0]["arguments"]["payload"]["proposal"]["spec"]["instructions"] = "Changed after review"
    result = run_typed_control_turn("Onaylıyorum.", mode="approve", session_state=state, client=None,
                                    db_name="unused", allow_approval_execute=True)
    assert not result.success and result.data["requires_reprepare"]
    assert not workflow_store.workflow_store_path().exists()


def test_current_revision_change_rejects_stale_compare_and_swap_approval(isolated_catalog):
    prepared, state = _prepared_state()
    conflict = deepcopy(_spec())
    conflict["instructions"] += " Eksikleri açıkça belirt."
    winner = workflow_store.save_prepared_workflow(workflow_store.prepare_workflow_save(conflict, workflow_id="stock-review"))
    result = run_typed_control_turn("Onaylıyorum.", mode="approve", session_state=state, client=None,
                                    db_name="unused", allow_approval_execute=True)
    assert not result.success
    assert workflow_store.read_workflow("stock-review") == winner
    assert winner.revision_id != prepared.data["revision_id"]
    assert len(workflow_store.list_workflow_revisions("stock-review")) == 1


def test_successful_save_replay_does_not_claim_an_old_revision_is_current(isolated_catalog):
    prepared, _ = _prepared_state()
    action = prepared.data["action"]
    audit = isolated_catalog / "replay-audit.jsonl"
    saved = execute_approved_operation(action, idempotency_key="workflow-current-test", audit_path=audit)
    assert saved.success, saved.message
    old = workflow_store.read_workflow("stock-review")
    changed = deepcopy(_spec())
    changed["parameter_schema"]["properties"]["days"]["maximum"] = 90
    current = workflow_store.save_prepared_workflow(workflow_store.prepare_workflow_save(
        changed, workflow_id=old.workflow_id, expected_revision_id=old.revision_id))
    stale_readback = verify_workflow_spec_save(action)
    assert not stale_readback.success
    assert stale_readback.data["current_head_matches_approved_revision"] is False
    replay = execute_approved_operation(action, idempotency_key="workflow-current-test", audit_path=audit)
    assert not replay.success
    assert workflow_store.read_workflow("stock-review") == current
    assert len(workflow_store.list_workflow_revisions("stock-review")) == 2


def test_review_includes_complete_parameter_contract_and_policy_flags(isolated_catalog):
    review = workflow_store.render_workflow_review(_spec())
    assert "days: tam sayı; zorunlu; en az: 1; en çok: 31" in review
    assert "Başka parametre kabul edilmez." in review
    assert "Her çalıştırmada güncel kaynak gerekir: evet." in review
    assert "Her işlem için güncel onay gerekir: evet." in review
