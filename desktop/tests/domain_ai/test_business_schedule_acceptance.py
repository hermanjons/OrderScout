"""Acceptance schedule clicks and evidence use real Qt/stores/shared runtime.

These are isolated contracts, not cloud acceptance. Only model JSON is scripted;
stock tools, report builder, checkpoint binding and scheduler storage are real.
"""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from AI.processors import task_store, workflow_scheduler, workflow_store
from AI.processors.business_acceptance_fixtures import WORKFLOW_ACCEPTANCE_SPEC, seed_business_fixture
from AI.processors.business_agent_acceptance_cli import (
    SCENARIOS, _source_snapshot, assert_isolated_scheduler, confirm_source_ui_schedule,
    prepare_source_ui_schedule, schedule_run_problems, schedule_task_binding_evidence,
    validate_business_turn,
)
from AI.processors.scheduled_task_runtime import run_scheduled_task
from AI.processors.session_state import AgentSessionState
from tests.domain_ai.test_scheduled_task_runtime import ScriptedClient


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def surface(tmp_path, monkeypatch, app):
    domain = tmp_path / "ai"
    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", domain)
    monkeypatch.setattr(workflow_scheduler, "AI_DOMAIN_ROOT", domain)
    monkeypatch.setattr(task_store, "TASK_STORE_DIR", domain / "tasks")
    workflow_store.save_prepared_workflow(workflow_store.prepare_workflow_save(deepcopy(WORKFLOW_ACCEPTANCE_SPEC)))
    parent = QWidget()
    parent._current_workflow_scope_bindings = lambda: {}
    dialogs = []
    def review():
        dialog, receipt = prepare_source_ui_schedule(parent,
            parameters=SCENARIOS["workflow_schedule_review"]["schedule_parameters"], isolation_root=tmp_path)
        dialogs.append(dialog)
        return dialog, receipt
    try:
        yield parent, review, tmp_path
    finally:
        for dialog in dialogs:
            dialog.close()
            dialog.deleteLater()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_real_library_typed_request_and_qt_review_pin_exact_utc_time_without_saving(surface):
    parent, review, root = surface
    before = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    dialog, receipt = review()
    after = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    configuration = receipt["proposal"]["schedule"]
    due = datetime.fromisoformat(configuration["first_due_at"])
    assert before <= due <= after and due.utcoffset().total_seconds() == 0
    assert due.second == due.microsecond == 0 and configuration["interval_seconds"] == 3600
    assert configuration["parameters"] == receipt["library_request"]["parameters"] == {"report_title": "Pilot Planlı Stok Raporu"}
    assert configuration["revision_id"] == receipt["library_request"]["revision_id"]
    assert configuration["spec_hash"] == receipt["library_request"]["spec_hash"]
    assert receipt["reviewed_text"] == dialog.review.toPlainText() and "UTC" in receipt["reviewed_text"]
    assert receipt["model_invoked"] is receipt["workflow_executed"] is receipt["schedule_saved"] is False
    assert not dialog.scheduler.path.exists() and dialog.scheduler.list_runs() == []
    assert not task_store.TASK_STORE_DIR.exists()


def test_real_confirmation_has_exact_independent_sqlite_readback_and_no_task_or_effect_approval(surface):
    parent, review, root = surface
    dialog, receipt = review()
    confirmed = confirm_source_ui_schedule(dialog, reviewed=receipt, isolation_root=root)
    assert dialog.saved and confirmed["effect_approval_granted"] is False
    independent = workflow_scheduler.WorkflowScheduler().list_schedules()
    assert independent == [confirmed["schedule"]]
    assert independent[0]["schedule"] == receipt["proposal"]["schedule"]
    assert independent[0]["schedule_hash"] == receipt["proposal"]["action_hash"]
    assert independent[0]["active_run_id"] is None and dialog.scheduler.list_runs() == []
    assert not task_store.TASK_STORE_DIR.exists() and not list(root.rglob("*.xlsx"))


@pytest.mark.parametrize("change", ["receipt", "interval", "parameters"])
def test_confirmation_rejects_changed_review_or_ui_request_without_writing_schedule(surface, change):
    parent, review, root = surface
    dialog, receipt = review()
    if change == "receipt":
        receipt = deepcopy(receipt)
        receipt["proposal"]["schedule"]["interval_seconds"] = 7200
    elif change == "interval":
        dialog.interval.setCurrentIndex(dialog.interval.findData(86400))
    else:
        dialog.request.parameters["report_title"] = "Unreviewed change"
    with pytest.raises(ValueError):
        confirm_source_ui_schedule(dialog, reviewed=receipt, isolation_root=root)
    assert not dialog.saved and not dialog.scheduler.path.exists()


def test_scheduler_storage_escape_is_rejected_before_confirmation_and_before_review_write(surface, monkeypatch):
    parent, review, root = surface
    outside = workflow_scheduler.WorkflowScheduler(root=root.parent / (root.name + "-outside"))
    with pytest.raises(ValueError, match="outside isolation"):
        assert_isolated_scheduler(outside, root)
    monkeypatch.setattr(workflow_scheduler, "WorkflowScheduler", lambda: outside)
    with pytest.raises(ValueError, match="outside isolation"):
        review()
    assert not outside.path.exists()


def test_schedule_control_phases_do_not_claim_a_model_response_or_allow_business_execution():
    turn = {"success": True, "answer": "Actual UI review", "runtime": {}, "execute": {"success": None}}
    for scenario in ("workflow_schedule_review", "workflow_schedule_approve"):
        assert validate_business_turn(turn, SCENARIOS[scenario], model="test/model") == []
        altered = {**turn, "execute": {"success": True}}
        assert "unexpected_execute_before_approval" in validate_business_turn(altered, SCENARIOS[scenario], model="test/model")
    problems = validate_business_turn(turn, SCENARIOS["workflow_schedule_run"], model="test/model")
    assert "live_model_response_missing" in problems and "exact_model_identity_not_proven" in problems
    assert "pending_immutable_action_missing" in problems


def test_actual_due_shared_runtime_proves_fresh_stock_and_bound_checkpoint_before_planning(surface, monkeypatch):
    parent, review, root = surface
    database = root / "business.sqlite3"
    seed_business_fixture(str(database), isolation_root=root)
    dialog, receipt = review()
    confirmed = confirm_source_ui_schedule(dialog, reviewed=receipt, isolation_root=root)
    scheduler = dialog.scheduler
    lease = scheduler.claim_due(owner_id="actual-acceptance-test")[0]
    binding_receipts = []
    original_attach = scheduler.attach_task_session
    def observe_binding(lease, session_id):
        original_attach(lease, session_id)
        binding_receipts.append(schedule_task_binding_evidence(scheduler, lease, session_id, isolation_root=root))
    monkeypatch.setattr(scheduler, "attach_task_session", observe_binding)
    client = ScriptedClient(scheduler, task_store.TASK_STORE_DIR, "Pilot Planlı Stok Raporu", root / "approved-stock.xlsx")
    result = run_scheduled_task(lease, scheduler=scheduler, client=client, provider_code="openrouter",
        model_name=client.model_name, db_name=str(database), allowed_scope_bindings={},
        current_session=AgentSessionState(goal="Prior completed task", status="complete"))
    assert result.success, (result.message, result.data)
    state = result.data["workflow_result"]["session_state"]
    turn = {"raw_turn_data": {"state": deepcopy(state), "scheduled_run": deepcopy(result.data["run"])}}
    assert schedule_run_problems(turn, schedule_receipt=confirmed, binding_receipts=binding_receipts) == []
    assert binding_receipts[0]["actual_task_session_id"] == client.bound_before_plan[0] == state["session_id"]
    assert binding_receipts[0]["submission_session_id"] != state["session_id"]
    assert not client.output.exists() and scheduler.claim_due(owner_id="duplicate") == []
    assert task_store.load_agent_task_state(state["session_id"]).status == "pending_approval"
    # Reject corrupt identities and borrowed/pre-existing approval evidence.
    for name, value in (("schedule_hash", "wrong"), ("session_id", "wrong"), ("status", "completed")):
        altered = deepcopy(turn)
        altered["raw_turn_data"]["scheduled_run"][name] = value
        assert "scheduled_run_not_bound_to_current_approved_schedule_and_task" in schedule_run_problems(
            altered, schedule_receipt=confirmed, binding_receipts=binding_receipts)
    for name, value in (("prior_approval_count", 1), ("planning_not_started", False),
                        ("submission_session_id", state["session_id"]), ("checkpoint_phase", "completed")):
        altered = deepcopy(binding_receipts)
        altered[0][name] = value
        assert "scheduled_actual_task_checkpoint_before_planning_missing" in schedule_run_problems(
            turn, schedule_receipt=confirmed, binding_receipts=altered)
    invocation = deepcopy(turn)
    invocation["raw_turn_data"]["state"]["active_entities"]["workflow_invocation"]["revision_id"] = "wrong"
    assert "scheduled_run_pinned_workflow_revision_mismatch" in schedule_run_problems(
        invocation, schedule_receipt=confirmed, binding_receipts=binding_receipts)
    # Only completed, observed tool receipts can establish stock values; answer
    # text, overwritten duplicate currencies and stale balances cannot pass.
    for mutation in ("stale_value", "duplicate_currency", "different_unit", "unobserved"):
        altered = deepcopy(turn)
        step = altered["raw_turn_data"]["state"]["completed_steps"][0]
        stock = step["result_data"]["tool_result"]
        if mutation == "stale_value":
            stock["stock_value_by_currency"][0]["amount"] = 999
        elif mutation == "duplicate_currency":
            stock["stock_value_by_currency"].insert(0, {"currency": "TRY", "amount": 999})
        elif mutation == "different_unit":
            next(row for row in stock["top_balances"] if row["sku"] == "PILOT-KUPA")["unit"] = "kg"
        else:
            step["verification_status"] = "failed"
        altered["answer"] = "Kupa 4 adet 400 TRY; filtre 3 adet 30 USD."
        assert "scheduled_fresh_stock_fixture_values_missing" in schedule_run_problems(
            altered, schedule_receipt=confirmed, binding_receipts=binding_receipts)


def test_live_acceptance_fingerprint_covers_actual_scheduler_ui_and_new_contracts():
    snapshot = _source_snapshot()
    assert snapshot["missing_requested_sources"] == []
    paths = {row["path"] for row in snapshot["files"]}
    assert {"AI/processors/workflow_scheduler.py", "AI/processors/scheduled_task_runtime.py",
            "AI/views/workflow_schedule_dialog.py", "AI/views/workflow_library.py",
            "tests/domain_ai/test_business_schedule_acceptance.py", "tests/domain_ai/test_chat_workflow_scheduler.py"} <= paths
