from copy import deepcopy
from datetime import datetime, timezone

import pytest
from PyQt6.QtCore import QDate, QDateTime, QTime, QTimeZone, Qt
from PyQt6.QtWidgets import QApplication, QDialog

from AI.processors import workflow_scheduler as schedules, workflow_store as workflows
from AI.views.workflow_library import WorkflowRunRequest
from AI.views.workflow_schedule_dialog import WorkflowScheduleDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(tmp_path, app):
    spec = {"schema_version": 1, "name": "Mağaza kontrolü", "instructions": "Güncel kaynakları okuyup eksikleri açıkla.",
            "objective_template": "Mağaza {{account}} için son {{days}} günü incele.",
            "parameter_schema": {"type": "object", "properties": {
                "account": {"type": "integer", "scope": "account_id"},
                "days": {"type": "integer", "minimum": 1, "maximum": 31}},
                "required": ["account", "days"], "additionalProperties": False},
            "source_policy": {"description": "Güncel kaynakları her çalışmada oku.", "requires_current_sources": True},
            "effect_policy": {"description": "Gerçek işlemleri güncel onaya sun.", "requires_current_approval": True}}
    workflow_root = tmp_path / "workflows"
    revision = workflows.save_prepared_workflow(workflows.prepare_workflow_save(spec), root=workflow_root)
    scheduler = schedules.WorkflowScheduler(root=tmp_path / "scheduler", workflow_root=workflow_root)
    parameters = {"account": 101, "days": 7}
    request = WorkflowRunRequest(revision.workflow_id, revision.revision_id, revision.spec.content_hash, parameters,
                                 workflows.render_workflow(revision.spec, parameters, allowed_scope_bindings={"account_id": [101]}))
    dialog = WorkflowScheduleDialog(scheduler=scheduler, request=request, allowed_scope_bindings={"account_id": [101]})
    return scheduler, request, dialog


def test_empty_schedule_manager_is_read_only_and_has_no_confirmation(tmp_path, app):
    scheduler = schedules.WorkflowScheduler(root=tmp_path)
    dialog = WorkflowScheduleDialog(scheduler=scheduler)
    assert dialog.list.count() == 0 and "Henüz planlı" in dialog.review.toPlainText()
    assert dialog.proposal is None and not dialog.confirm.isEnabled()
    assert not scheduler.path.exists()
    dialog.deleteLater()


def test_local_qt_time_is_converted_to_aware_utc_before_effect_free_review(setup):
    scheduler, request, dialog = setup
    selected = QDateTime(QDate(2026, 10, 15), QTime(11, 30), Qt.TimeSpec.LocalTime)
    assert selected.toPyDateTime().tzinfo is None
    dialog.first_due.setDateTime(selected)
    dialog.prepare_button.click()
    assert not dialog.error.text() and dialog.confirm.isEnabled()
    due = datetime.fromisoformat(dialog.proposal["schedule"]["first_due_at"])
    assert due.tzinfo is not None and due.utcoffset().total_seconds() == 0
    assert due.timestamp() == selected.toMSecsSinceEpoch() / 1000
    assert "11:30" in dialog.review.toPlainText() and "UTC" in dialog.review.toPlainText()
    assert dialog.proposal["schedule"]["parameters"] == request.parameters
    assert not scheduler.path.exists()
    dialog.deleteLater()


def test_explicit_istanbul_timezone_selection_preserves_exact_three_hour_offset(setup):
    scheduler, request, dialog = setup
    selected = QDateTime(QDate(2026, 10, 15), QTime(11, 30), QTimeZone(b"Europe/Istanbul"))
    assert selected.isValid()
    dialog.first_due.setDateTime(selected)
    dialog._prepare()
    assert dialog.proposal["schedule"]["first_due_at"] == "2026-10-15T08:30:00+00:00"
    assert not scheduler.path.exists()
    dialog.deleteLater()


@pytest.mark.parametrize("change", ["interval", "date"])
def test_edited_time_or_interval_invalidates_review_and_requires_a_new_review(setup, change):
    scheduler, request, dialog = setup
    dialog._prepare()
    original = deepcopy(dialog.proposal)
    if change == "interval":
        dialog.interval.setCurrentIndex(2)
    else:
        dialog.first_due.setDateTime(dialog.first_due.dateTime().addSecs(3600))
    assert dialog.proposal is None and not dialog.confirm.isEnabled()
    assert "yeniden gözden geçir" in dialog.error.text()
    dialog._confirm()
    assert not scheduler.path.exists() and dialog.saved is False
    dialog._prepare()
    assert dialog.proposal["action_hash"] != original["action_hash"]
    dialog._confirm()
    assert dialog.saved and dialog.result() == QDialog.DialogCode.Accepted
    saved = scheduler.list_schedules()[0]
    assert saved["schedule_hash"] == dialog.proposal["action_hash"]
    assert saved["schedule"] == dialog.proposal["schedule"]
    dialog.deleteLater()


def test_final_confirmation_commits_only_exact_reviewed_proposal(setup):
    scheduler, request, dialog = setup
    dialog._prepare()
    reviewed = deepcopy(dialog.proposal)
    dialog.confirm.click()
    assert dialog.saved and dialog.result() == QDialog.DialogCode.Accepted
    row = scheduler.list_schedules()[0]
    assert row["schedule"] == reviewed["schedule"] and row["schedule_hash"] == reviewed["action_hash"]
    assert scheduler.list_runs() == []
    dialog.deleteLater()


def test_mutated_even_rehashed_public_proposal_cannot_replace_what_user_reviewed(setup):
    scheduler, request, dialog = setup
    dialog._prepare()
    original = dialog.proposal
    configuration = deepcopy(original["schedule"])
    configuration["interval_seconds"] = 3600
    dialog.proposal = schedules._prepared("workflow.schedule.save", original["schedule_id"], "", configuration)
    dialog._confirm()
    assert not scheduler.path.exists() and dialog.saved is False
    assert dialog.proposal is None and not dialog.confirm.isEnabled()
    assert "teklif değişti" in dialog.error.text()
    dialog.deleteLater()


def test_changed_request_parameters_require_review_and_cannot_save_prior_or_new_unreviewed_scope(setup):
    scheduler, request, dialog = setup
    dialog._prepare()
    request.parameters["days"] = 14
    dialog._confirm()
    assert not scheduler.path.exists() and dialog.saved is False
    assert "parametreleri değişti" in dialog.error.text()
    assert dialog.proposal is None
    dialog._prepare()
    assert dialog.proposal["schedule"]["parameters"]["days"] == 14
    dialog._confirm()
    assert scheduler.list_schedules()[0]["schedule"]["parameters"]["days"] == 14
    dialog.deleteLater()


def test_invalid_or_changed_revision_does_not_leave_a_saveable_proposal(setup):
    scheduler, request, dialog = setup
    bad_request = WorkflowRunRequest(request.workflow_id, request.revision_id, "0" * 64, request.parameters, request.objective)
    dialog.request = bad_request
    dialog._prepare()
    assert dialog.proposal is None and not dialog.confirm.isEnabled()
    assert "yönerge değişti" in dialog.error.text()
    assert not scheduler.path.exists()
    dialog.deleteLater()


def test_manager_reviews_exact_cancellation_and_preserves_existing_run_receipts(setup, app):
    scheduler, request, creator = setup
    creator._prepare()
    creator._confirm()
    saved = scheduler.list_schedules()[0]
    manager = WorkflowScheduleDialog(scheduler=scheduler)
    manager.list.setCurrentRow(0)
    assert manager.proposal["action_type"] == "workflow.schedule.cancel"
    assert manager.proposal["expected_schedule_hash"] == saved["schedule_hash"]
    assert "iptal" in manager.confirm.text() and manager.confirm.isEnabled()
    manager.confirm.click()
    assert manager.saved and scheduler.list_schedules()[0]["status"] == "cancelled"
    assert scheduler.list_runs() == []
    creator.deleteLater()
    manager.deleteLater()


def test_concurrent_schedule_update_rejects_stale_reviewed_cancellation(setup):
    scheduler, request, creator = setup
    creator._prepare()
    creator._confirm()
    original = scheduler.list_schedules()[0]
    manager = WorkflowScheduleDialog(scheduler=scheduler)
    manager.list.setCurrentRow(0)
    configuration = original["schedule"]
    update = scheduler.prepare_schedule_save(request.workflow_id, revision_id=request.revision_id, parameters=request.parameters,
                interval_seconds=3600, first_due_at=configuration["first_due_at"], schedule_id=original["schedule_id"],
                expected_schedule_hash=original["schedule_hash"], allowed_scope_bindings={"account_id": [101]})
    scheduler.save_prepared_schedule(update, confirmed_action_hash=update["action_hash"], approved_by="other-user-action")
    manager._confirm()
    assert manager.saved is False and not manager.confirm.isEnabled()
    assert "kaydedilemedi" in manager.error.text()
    assert scheduler.list_schedules()[0]["status"] == "active"
    assert scheduler.list_schedules()[0]["schedule_hash"] == update["action_hash"]
    creator.deleteLater()
    manager.deleteLater()
