from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

import pytest

from AI.processors import workflow_scheduler as schedules, workflow_store as workflows
from AI.processors import task_store
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from Feedback.processors.pipeline import Result


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


def _spec():
    return {"schema_version": 1, "name": "Current source review",
            "instructions": "Read current evidence and retain its scope. Prepare effects for current confirmation.",
            "objective_template": "Inspect current account {{account_id}} for {{days}} days.",
            "parameter_schema": {"type": "object", "properties": {
                "account_id": {"type": "integer", "minimum": 1, "scope": "account_id"},
                "days": {"type": "integer", "minimum": 1, "maximum": 30}},
                "required": ["account_id", "days"], "additionalProperties": False},
            "source_policy": {"description": "Read current sources afresh; historical results are not current evidence.", "requires_current_sources": True},
            "effect_policy": {"description": "Obtain the user's current confirmation before each effect.", "requires_current_approval": True}}


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    workflow_root = tmp_path / "workflows"
    revision = workflows.save_prepared_workflow(workflows.prepare_workflow_save(_spec(), workflow_id="current-review"), root=workflow_root)
    scheduler = schedules.WorkflowScheduler(root=tmp_path / "scheduler", workflow_root=workflow_root, clock=clock, lease_seconds=60)
    return scheduler, clock, revision


def _prepare(setup, **overrides):
    scheduler, clock, revision = setup
    fields = {"revision_id": revision.revision_id, "parameters": {"account_id": 101, "days": 7},
              "interval_seconds": 60, "first_due_at": clock(), "allowed_scope_bindings": {"account_id": [101]},
              "budget": {"max_steps": 8, "max_replans": 1}}
    fields.update(overrides)
    return scheduler.prepare_schedule_save(revision.workflow_id, **fields)


def _approve(scheduler, proposal):
    return scheduler.save_prepared_schedule(proposal, confirmed_action_hash=proposal["action_hash"], approved_by="test-human")


def _saved(setup, **overrides):
    proposal = _prepare(setup, **overrides)
    _approve(setup[0], proposal)
    return proposal


def _complete(goal, **kwargs):
    state = deepcopy(kwargs["session_state"])
    state["status"] = "complete"
    kwargs["progress_callback"](25, "Source read completed")
    return Result.ok("Current workflow completed.", close_dialog=False, data={"state": state})


def _dispatch(scheduler, **kwargs):
    return scheduler.dispatch_due(owner_id="worker", runner=kwargs.pop("runner", _complete), planner_client=kwargs.pop("planner_client", object()),
                                  allowed_scope_bindings=kwargs.pop("allowed_scope_bindings", {"account_id": [101]}), **kwargs)


def test_prepare_is_inspectable_revision_pinned_and_never_creates_scheduler_storage(setup):
    scheduler, clock, revision = setup
    proposal = _prepare(setup, first_due_at="2026-10-08T11:00:00+03:00")
    assert proposal["schedule"]["first_due_at"] == "2026-10-08T08:00:00+00:00"
    assert proposal["schedule"]["pinned_spec"] == revision.spec.to_dict()
    assert proposal["schedule"]["revision_id"] == revision.revision_id
    assert proposal["requires_current_approval"] is True
    assert not scheduler.path.exists()
    assert scheduler.list_schedules() == [] and scheduler.list_runs() == []


@pytest.mark.parametrize("bad_interval", [0, 59, True, "60", 366 * 86400 + 1])
def test_interval_bounds_and_types_are_authoritative(setup, bad_interval):
    with pytest.raises(schedules.ScheduleValidationError):
        _prepare(setup, interval_seconds=bad_interval)


@pytest.mark.parametrize("bad_time", ["2026-10-08T08:00:00", "today", None])
def test_naive_or_unparsed_times_are_rejected(setup, bad_time):
    with pytest.raises(schedules.ScheduleValidationError):
        _prepare(setup, first_due_at=bad_time)


def test_exact_human_confirmation_is_required_and_has_no_effect_authority(setup):
    scheduler = setup[0]
    proposal = _prepare(setup)
    for confirmation, human in (("0" * 64, "human"), (proposal["action_hash"], "")):
        with pytest.raises(schedules.ScheduleValidationError):
            scheduler.save_prepared_schedule(proposal, confirmed_action_hash=confirmation, approved_by=human)
    assert not scheduler.path.exists()
    result = _approve(scheduler, proposal)
    assert result.success and result.data["effect_approval_granted"] is False
    assert _approve(scheduler, proposal).data == result.data
    assert len(scheduler.list_schedules()) == 1


@pytest.mark.parametrize("changed", ["interval", "parameters", "budget", "spec", "extra", "approval"])
def test_changed_reviewed_payload_cannot_be_saved(setup, changed):
    scheduler = setup[0]
    original = _prepare(setup)
    forged = deepcopy(original)
    if changed == "interval":
        forged["schedule"]["interval_seconds"] = 120
    elif changed == "parameters":
        forged["schedule"]["parameters"]["account_id"] = 999
    elif changed == "budget":
        forged["schedule"]["budget"]["max_steps"] = 99
    elif changed == "spec":
        forged["schedule"]["pinned_spec"]["instructions"] = "Forged alternative objective"
    elif changed == "extra":
        forged["approved_action"] = {"execute_enabled": True}
    else:
        forged["requires_current_approval"] = False
    with pytest.raises((schedules.ScheduleValidationError, schedules.ScheduleIntegrityError)):
        scheduler.save_prepared_schedule(forged, confirmed_action_hash=original["action_hash"], approved_by="human")
    assert not scheduler.path.exists()


def test_cas_update_cancel_and_old_idempotent_proposals_never_rewind_head(setup):
    scheduler, clock, revision = setup
    first = _saved(setup)
    update = _prepare(setup, schedule_id=first["schedule_id"], expected_schedule_hash=first["action_hash"], interval_seconds=120)
    second = _approve(scheduler, update)
    assert second.data["schedule"]["schedule_hash"] == update["action_hash"]
    _approve(scheduler, first)
    assert scheduler.list_schedules()[0]["schedule_hash"] == update["action_hash"]
    stale = _prepare(setup, schedule_id=first["schedule_id"], expected_schedule_hash=first["action_hash"], interval_seconds=180)
    with pytest.raises(schedules.ScheduleConflictError):
        _approve(scheduler, stale)
    cancelled = scheduler.prepare_schedule_cancel(first["schedule_id"], expected_schedule_hash=update["action_hash"])
    scheduler.cancel_prepared_schedule(cancelled, confirmed_action_hash=cancelled["action_hash"], approved_by="human")
    assert scheduler.list_schedules()[0]["status"] == "cancelled"
    assert scheduler.list_schedules()[0]["next_due_at"] is None
    assert scheduler.claim_due(owner_id="worker") == []
    with pytest.raises(schedules.ScheduleConflictError):
        _approve(scheduler, _prepare(setup, schedule_id=first["schedule_id"], expected_schedule_hash=update["action_hash"]))


def test_not_due_and_missed_intervals_never_form_a_catchup_avalanche(setup):
    scheduler, clock, revision = setup
    first = _saved(setup, first_due_at=clock() + timedelta(seconds=60))
    assert scheduler.claim_due(owner_id="worker") == []
    clock.advance(60 + 7 * 86400 + 25)
    outcome = _dispatch(scheduler)
    assert outcome.success and outcome.data["claimed_count"] == 1
    run = outcome.data["runs"][0]
    assert run["receipt"]["skipped_intervals"] == 7 * 24 * 60
    assert scheduler.claim_due(owner_id="worker") == []
    next_due = datetime.fromisoformat(scheduler.list_schedules()[0]["next_due_at"])
    assert clock() < next_due <= clock() + timedelta(seconds=60)


def test_unstarted_expired_lease_is_reclaimed_with_same_id_and_fencing_token(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    first = scheduler.claim_due(owner_id="first")[0]
    assert scheduler.claim_due(owner_id="other") == []
    clock.advance(61)
    second = scheduler.claim_due(owner_id="second")[0]
    assert second.run_id == first.run_id and second.lease_token != first.lease_token
    assert "lease_token" not in second.to_dict() and second.lease_token not in repr(second)
    with pytest.raises(schedules.ScheduleConflictError):
        scheduler.execute_lease(first, runner=_complete, planner_client=object(), allowed_scope_bindings={"account_id": [101]})
    result = scheduler.execute_lease(second, runner=_complete, planner_client=object(), allowed_scope_bindings={"account_id": [101]})
    assert result.data["run"]["attempts"] == 2
    assert result.data["run"]["status"] == "completed"


def test_deterministic_run_receipt_is_not_reexecuted_when_worker_retries(setup):
    scheduler = setup[0]
    _saved(setup)
    lease = scheduler.claim_due(owner_id="worker")[0]
    called = []
    def runner(goal, **kwargs):
        called.append(goal)
        return _complete(goal, **kwargs)
    first = scheduler.execute_lease(lease, runner=runner, planner_client=object(), allowed_scope_bindings={"account_id": [101]})
    repeated = scheduler.execute_lease(lease, runner=runner, planner_client=object(), allowed_scope_bindings={"account_id": [101]})
    assert first.data["executed"] is True and repeated.data["executed"] is False
    assert len(called) == 1 and len(scheduler.list_runs()) == 1


def test_workflow_revision_current_provider_and_bounded_fresh_runtime_are_used(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    changed = revision.spec.to_dict()
    changed["instructions"] = "A later workflow revision with different instructions."
    later = workflows.save_prepared_workflow(workflows.prepare_workflow_save(changed, workflow_id=revision.workflow_id,
                                             expected_revision_id=revision.revision_id), root=scheduler.workflow_root)
    previous = AgentSessionState(goal="Prior completed task", active_domain="general", status="complete")
    previous.completed_steps = [AgentTaskStep(index=1, prompt="Prior data", status="completed")]
    previous.last_tool_results = [{"count": 999}]
    previous.action_history = [{"approved_by": "previous-approval"}]
    previous.active_entities["runtime_context"] = {"provider_id": 4, "model_name": "current/provider-model", "api_key": "do-not-forward"}
    planner, received, progress = object(), [], []
    def runner(goal, **kwargs):
        received.append((goal, kwargs))
        return _complete(goal, **kwargs)
    result = _dispatch(scheduler, runner=runner, planner_client=planner, current_session=previous,
                       runner_options={"max_steps": 999, "max_replans": 999, "progress_callback": lambda *args: progress.append(args)})
    assert result.data["runs"][0]["status"] == "completed"
    goal, options = received[0]
    assert revision.spec.to_dict()["instructions"] in goal and changed["instructions"] not in goal
    assert options["planner_client"] is planner and options["max_steps"] == 8 and options["max_replans"] == 1
    fresh = options["session_state"]
    assert fresh["session_id"] != previous.session_id
    for field in ("completed_steps", "last_tool_results", "pending_actions", "action_history"):
        assert fresh[field] == []
    assert fresh["active_entities"]["workflow_invocation"]["revision_id"] == revision.revision_id
    assert fresh["active_entities"]["workflow_invocation"]["revision_id"] != later.revision_id
    assert fresh["active_entities"]["runtime_context"] == {"provider_id": 4, "model_name": "current/provider-model"}
    assert progress == [(25, "Source read completed")]
    assert "previous-approval" not in json.dumps(scheduler.list_runs()) and "do-not-forward" not in json.dumps(scheduler.list_runs())


@pytest.mark.parametrize("status", ["pending_approval", "paused"])
def test_active_prior_pending_or_paused_run_blocks_all_new_scheduled_executions(setup, status):
    scheduler, clock, revision = setup
    _saved(setup)
    received = []
    def runner(goal, **kwargs):
        received.append(goal)
        state = deepcopy(kwargs["session_state"])
        state["status"] = status
        if status == "pending_approval":
            state["pending_actions"] = [{"action_id": "current-only", "approval_required": True}]
        return Result.ok("Current run requires attention", close_dialog=False, data={"state": state})
    result = _dispatch(scheduler, runner=runner)
    run = result.data["runs"][0]
    assert run["status"] == ("awaiting_approval" if status == "pending_approval" else "paused")
    clock.advance(10 * 86400)
    assert _dispatch(scheduler, runner=runner).data["claimed_count"] == 0
    assert len(received) == 1 and len(scheduler.list_runs()) == 1
    assert "current-only" not in json.dumps(scheduler.list_runs())
    assert run["session_id"]


def test_current_unrelated_pending_session_is_admission_blocked_without_a_new_goal(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    current = AgentSessionState(goal="Interactive current approval", status="pending_approval", session_id="interactive-task")
    calls = []
    result = _dispatch(scheduler, runner=lambda *_args, **_kwargs: calls.append("unexpected"), current_session=current)
    assert result.data["runs"][0]["status"] == "blocked" and calls == []
    run = scheduler.list_runs()[0]
    assert run["session_id"] is None and run["receipt"]["blocked_by_session_id"] == current.session_id
    assert scheduler.reconcile_run(run["run_id"], session_loader=lambda _identity: current)["status"] == "blocked"
    current.status = "complete"
    scheduler.reconcile_run(run["run_id"], session_loader=lambda _identity: current)
    assert len(scheduler.claim_due(owner_id="worker")) == 1


def test_scope_parameters_are_revalidated_at_each_execution_and_failure_is_listable(setup):
    scheduler = setup[0]
    _saved(setup)
    calls = []
    result = _dispatch(scheduler, runner=lambda *_args, **_kwargs: calls.append("unexpected"), allowed_scope_bindings={"account_id": [999]})
    run = result.data["runs"][0]
    assert run["status"] == "failed" and calls == []
    assert run["execution_started_at"] is None and run["receipt"]["reason"] == "WorkflowValidationError"
    assert scheduler.list_schedules()[0]["active_run_id"] is None


def test_started_exception_never_replays_without_trusted_checkpoint(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    calls = []
    def runner(_goal, **_kwargs):
        calls.append("started")
        raise RuntimeError("fixture exception containing secrets is never persisted")
    result = _dispatch(scheduler, runner=runner)
    assert result.data["runs"][0]["status"] == "recovery_required"
    clock.advance(3600)
    assert scheduler.claim_due(owner_id="another") == []
    assert calls == ["started"]
    assert "containing secrets" not in json.dumps(scheduler.list_runs())


def test_started_expired_run_reconciles_exact_task_checkpoint_without_running_it(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    lease = scheduler.claim_due(owner_id="worker")[0]
    scheduler._begin_execution(lease, {"session_id": "submission-context"})
    scheduler.attach_task_session(lease, "actual-task")
    clock.advance(61)
    assert scheduler.claim_due(owner_id="next") == []
    assert scheduler.list_runs()[0]["status"] == "recovery_required"
    pending = AgentSessionState(goal="Existing scheduled task", session_id="actual-task", status="pending_approval")
    assert scheduler.reconcile_run(lease.run_id, session_loader=lambda _identity: pending)["status"] == "awaiting_approval"
    pending.status = "complete"
    final = scheduler.reconcile_run(lease.run_id, session_loader=lambda _identity: pending)
    assert final["status"] == "completed" and scheduler.list_schedules()[0]["active_run_id"] is None
    with pytest.raises(schedules.ScheduleIntegrityError):
        other = scheduler.claim_due(owner_id="next")[0]
        scheduler._begin_execution(other, {"session_id": "new-context"})
        scheduler.attach_task_session(other, "actual-next-task")
        scheduler.reconcile_run(other.run_id, session_loader=lambda _identity: {"session_id": "forged", "status": "complete"})


def test_update_or_cancel_invalidates_unstarted_lease_but_never_replays_it(setup):
    scheduler, clock, revision = setup
    first = _saved(setup)
    lease = scheduler.claim_due(owner_id="worker")[0]
    cancellation = scheduler.prepare_schedule_cancel(first["schedule_id"], expected_schedule_hash=first["action_hash"])
    scheduler.cancel_prepared_schedule(cancellation, confirmed_action_hash=cancellation["action_hash"], approved_by="human")
    calls = []
    result = scheduler.execute_lease(lease, runner=lambda *_args, **_kwargs: calls.append("unexpected"), planner_client=object())
    assert result.data["executed"] is False and calls == []
    assert result.data["run"]["receipt"]["reason"] == "schedule_cancelled"


def test_cancellation_during_execution_stops_future_runs_and_preserves_current_receipt(setup):
    scheduler, clock, revision = setup
    first = _saved(setup)
    def runner(goal, **kwargs):
        proposal = scheduler.prepare_schedule_cancel(first["schedule_id"], expected_schedule_hash=first["action_hash"])
        scheduler.cancel_prepared_schedule(proposal, confirmed_action_hash=proposal["action_hash"], approved_by="human")
        return _complete(goal, **kwargs)
    result = _dispatch(scheduler, runner=runner)
    assert result.data["runs"][0]["status"] == "completed"
    clock.advance(3600)
    assert scheduler.claim_due(owner_id="next") == []
    assert scheduler.list_schedules()[0]["status"] == "cancelled"


def test_separate_scheduler_workers_atomically_claim_a_due_run_once(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    barrier = threading.Barrier(2)
    def claim(owner):
        other = schedules.WorkflowScheduler(root=scheduler.root, workflow_root=scheduler.workflow_root, clock=clock, lease_seconds=60)
        barrier.wait()
        return other.claim_due(owner_id=owner)
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(claim, ["worker-a", "worker-b"]))
    assert sorted(len(value) for value in outcomes) == [0, 1]
    assert len(scheduler.list_runs()) == 1


def test_returned_actual_checkpoint_identity_replaces_submission_context_and_reconciles(setup, tmp_path):
    scheduler, clock, revision = setup
    _saved(setup)
    submission_ids = []
    checkpoint_root = tmp_path / "actual-checkpoints"
    def runner(goal, **kwargs):
        submission_ids.append(kwargs["session_state"]["session_id"])
        actual = AgentSessionState(goal=goal, session_id="actual-created-task", status="paused")
        task_store.save_agent_task_state(actual, root=checkpoint_root)
        return Result.ok("User guidance required", close_dialog=False, data={"state": actual.to_dict()})
    result = _dispatch(scheduler, runner=runner)
    run = result.data["runs"][0]
    assert run["session_id"] == "actual-created-task" != submission_ids[0]
    assert run["receipt"]["submission_session_id"] == submission_ids[0]
    actual = task_store.load_agent_task_state(run["session_id"], root=checkpoint_root)
    actual.status = "complete"
    task_store.save_agent_task_state(actual, root=checkpoint_root)
    reconciled = scheduler.reconcile_run(run["run_id"], session_loader=lambda identity: task_store.load_agent_task_state(identity, root=checkpoint_root))
    assert reconciled["status"] == "completed"
    assert scheduler.list_schedules()[0]["active_run_id"] is None


@pytest.mark.parametrize("returned", [None, {}, {"status": "complete"}, {"session_id": "actual-task", "status": "unknown"}])
def test_unknown_returned_execution_state_cannot_claim_completion_or_trigger_fresh_run(setup, returned):
    scheduler, clock, revision = setup
    _saved(setup)
    calls = []
    def runner(_goal, **_kwargs):
        calls.append("executed")
        return Result.ok("The model says it finished", close_dialog=False, data={"state": returned})
    result = _dispatch(scheduler, runner=runner)
    run = result.data["runs"][0]
    assert run["status"] == "recovery_required"
    assert run["receipt"]["success"] is False
    assert result.data["results"][0]["success"] is False
    assert "model says" not in result.data["results"][0]["message"]
    clock.advance(10 * 86400)
    assert scheduler.claim_due(owner_id="retry") == []
    assert calls == ["executed"]


def test_non_result_from_started_runner_is_recovery_required_and_not_replayed(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    result = _dispatch(scheduler, runner=lambda *_args, **_kwargs: {"status": "complete"})
    assert result.data["runs"][0]["status"] == "recovery_required"
    assert result.data["runs"][0]["receipt"]["reason"] == "TypeError"
    clock.advance(3600)
    assert scheduler.claim_due(owner_id="next") == []


def test_expired_started_worker_is_fenced_from_task_binding_and_receipt_mutation(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    lease = scheduler.claim_due(owner_id="original")[0]
    scheduler._begin_execution(lease, {"session_id": "submission-context"})
    scheduler.attach_task_session(lease, "actual-task")
    clock.advance(61)
    assert scheduler.claim_due(owner_id="recovery-worker") == []
    for operation in (
        lambda: scheduler.heartbeat(lease),
        lambda: scheduler.attach_task_session(lease, "actual-task"),
        lambda: scheduler._settle(lease, Result.ok("late", data={"state": {"session_id": "actual-task", "status": "complete"}})),
    ):
        with pytest.raises(schedules.ScheduleConflictError):
            operation()
    checkpoint = AgentSessionState(goal="Actual task", session_id="actual-task", status="paused")
    assert scheduler.reconcile_run(lease.run_id, session_loader=lambda _identity: checkpoint)["status"] == "paused"
    assert scheduler.list_runs()[0]["owner_id"] == "recovery-worker"


def test_actual_task_binding_is_immutable_and_does_not_accept_a_second_returned_session(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    lease = scheduler.claim_due(owner_id="worker")[0]
    scheduler._begin_execution(lease, {"session_id": "submission-context"})
    scheduler.attach_task_session(lease, "actual-task")
    with pytest.raises(schedules.ScheduleIntegrityError):
        scheduler.attach_task_session(lease, "different-task")
    with pytest.raises(schedules.ScheduleIntegrityError):
        scheduler._settle(lease, Result.ok("different", data={"state": {"session_id": "different-task", "status": "complete"}}))
    assert scheduler.list_runs()[0]["session_id"] == "actual-task"
    assert scheduler.list_runs()[0]["status"] == "running"


@pytest.mark.parametrize("identity", ["../outside", "Mixed-Case", "con", "task ", "", "x" * 97])
def test_task_checkpoint_binding_uses_canonical_task_store_identity_grammar(setup, identity):
    scheduler = setup[0]
    _saved(setup)
    lease = scheduler.claim_due(owner_id="worker")[0]
    scheduler._begin_execution(lease, {"session_id": "submission-context"})
    with pytest.raises(schedules.ScheduleIntegrityError):
        scheduler.attach_task_session(lease, identity)
    assert scheduler.list_runs()[0]["session_id"] is None


def test_missing_trusted_checkpoint_preserves_uncertain_execution_for_attention(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    lease = scheduler.claim_due(owner_id="worker")[0]
    scheduler._begin_execution(lease, {"session_id": "submission-context"})
    scheduler.attach_task_session(lease, "actual-task")
    clock.advance(61)
    scheduler.claim_due(owner_id="recovery")
    def missing(_identity):
        raise FileNotFoundError("Actual checkpoint missing")
    assert scheduler.reconcile_run(lease.run_id, session_loader=missing)["status"] == "recovery_required"
    assert scheduler.claim_due(owner_id="next") == []


def test_schedule_cannot_borrow_a_different_human_confirmed_schedule_identity(setup):
    scheduler = setup[0]
    first = _saved(setup)
    second = _saved(setup, interval_seconds=120)
    with sqlite3.connect(scheduler.path) as connection:
        connection.execute("UPDATE schedules SET schedule_hash=?,configuration_json=? WHERE schedule_id=?",
                           (second["action_hash"], schedules._canonical(second["schedule"]), first["schedule_id"]))
    with pytest.raises(schedules.ScheduleIntegrityError):
        scheduler.claim_due(owner_id="worker", max_runs=2)
    with pytest.raises(schedules.ScheduleIntegrityError):
        scheduler.list_schedules()


@pytest.mark.parametrize("unsupported", ["approved_action", "tool_results", "plan", "execute_enabled", "executor"])
def test_runtime_options_never_inject_execution_or_prior_approval_authority(setup, unsupported):
    scheduler = setup[0]
    _saved(setup)
    calls = []
    with pytest.raises(schedules.ScheduleValidationError):
        _dispatch(scheduler, runner=lambda *_args, **_kwargs: calls.append("executed"), runner_options={unsupported: {"payload": "anything"}})
    assert calls == [] and scheduler.list_runs()[0]["execution_started_at"] is None


def test_explicit_current_provider_metadata_is_used_but_secret_metadata_is_rejected_before_execution(setup):
    scheduler = setup[0]
    _saved(setup)
    received = []
    def runner(goal, **kwargs):
        received.append(kwargs["session_state"]["active_entities"]["runtime_context"])
        return _complete(goal, **kwargs)
    result = _dispatch(scheduler, runner=runner, runner_options={"runtime_context": {"provider_id": 8, "model_name": "current/model"}})
    assert result.data["runs"][0]["status"] == "completed"
    assert received == [{"provider_id": 8, "model_name": "current/model"}]
    clock = setup[1]
    clock.advance(61)
    failed = _dispatch(scheduler, runner=runner, runner_options={"runtime_context": {"api_key": "never-forward"}})
    assert failed.data["runs"][0]["status"] == "failed" and len(received) == 1
    assert "never-forward" not in json.dumps(scheduler.list_runs())


def test_actual_progress_renews_long_execution_lease_without_enabling_another_worker(setup):
    scheduler, clock, revision = setup
    _saved(setup)
    notices = []
    def runner(goal, **kwargs):
        clock.advance(50)
        kwargs["progress_callback"](20, "Observed current source")
        clock.advance(40)
        # The original 60-second lease has elapsed, but real progress renewed it.
        assert scheduler.claim_due(owner_id="other-worker") == []
        return _complete(goal, **kwargs)
    result = _dispatch(scheduler, runner=runner, runner_options={"progress_callback": lambda *args: notices.append(args)})
    assert result.data["runs"][0]["status"] == "completed"
    assert notices == [(20, "Observed current source"), (25, "Source read completed")]


def test_interrupted_native_sqlite_transaction_recovers_without_partial_intent_or_double_run(setup):
    scheduler = setup[0]
    saved = _saved(setup)
    script = (
        "import os, sqlite3, sys\n"
        "connection = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
        "connection.execute('PRAGMA synchronous=EXTRA')\n"
        "connection.execute('BEGIN IMMEDIATE')\n"
        "connection.execute('UPDATE schedules SET schedule_hash=? WHERE schedule_id=?', ('0'*64, sys.argv[2]))\n"
        "os._exit(73)\n"
    )
    interrupted = subprocess.run([sys.executable, "-c", script, str(scheduler.path), saved["schedule_id"]], capture_output=True, timeout=20)
    assert interrupted.returncode == 73
    reopened = schedules.WorkflowScheduler(root=scheduler.root, workflow_root=scheduler.workflow_root, clock=setup[1], lease_seconds=60)
    assert reopened.list_schedules()[0]["schedule_hash"] == saved["action_hash"]
    assert len(reopened.claim_due(owner_id="after-restart")) == 1
    assert reopened.claim_due(owner_id="duplicate-worker") == []


def test_exact_schedule_approval_and_audit_events_are_immutable_in_native_storage(setup):
    scheduler = setup[0]
    proposal = _saved(setup)
    scheduler.claim_due(owner_id="worker")
    with sqlite3.connect(scheduler.path) as connection:
        for statement, values in (
            ("UPDATE schedule_actions SET approved_by='another' WHERE action_hash=?", (proposal["action_hash"],)),
            ("DELETE FROM schedule_actions WHERE action_hash=?", (proposal["action_hash"],)),
            ("UPDATE run_events SET event_type='pretended_complete'", ()),
            ("DELETE FROM run_events", ()),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement, values)
    assert scheduler.list_schedules()[0]["schedule_hash"] == proposal["action_hash"]
    assert scheduler.list_runs()[0]["status"] == "leased"


def test_unrelated_native_database_is_rejected_and_never_reinitialised(setup):
    scheduler = setup[0]
    scheduler.root.mkdir()
    with sqlite3.connect(scheduler.path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('retained')")
    with pytest.raises(schedules.ScheduleIntegrityError):
        scheduler.list_schedules()
    with pytest.raises(schedules.ScheduleIntegrityError):
        scheduler.claim_due(owner_id="worker")
    with sqlite3.connect(scheduler.path) as connection:
        assert connection.execute("SELECT value FROM unrelated").fetchone()[0] == "retained"
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='schedules'").fetchone() is None
