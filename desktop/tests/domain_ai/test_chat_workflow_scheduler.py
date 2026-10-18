"""Qt scheduling admission and selected-model handoff with real schedule stores."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from PyQt6.QtWidgets import QApplication

from AI.processors import task_store, workflow_store
from AI.processors.business_acceptance_fixtures import WORKFLOW_ACCEPTANCE_SPEC, seed_business_fixture
from AI.processors.cloud_runtime import _record_invocation_outcome
from AI.processors.orders_source_ui_human_recheck_cli import _capture_turn
from AI.processors.session_state import AgentSessionState
from AI.processors.workflow_scheduler import WorkflowScheduler
from AI.views import chat_tab
from AI.views.chat_tab import AI_CHAT_SOURCE_CLOUD_VALUE
from Feedback.processors.pipeline import Result
from tests.domain_ai.test_scheduled_task_runtime import ScriptedClient


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in self.callbacks:
            callback(*args)


class DeferredWorker:
    def __init__(self, func, *args, parent=None, **kwargs):
        self.func, self.args, self.kwargs = func, args, kwargs
        self.result_ready, self.progress, self.finished = Signal(), Signal(), Signal()
        self.running = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running


class LedgerScriptedClient(ScriptedClient):
    """Record each actual scripted invocation using the provider ledger writer."""
    def __init__(self, *args):
        super().__init__(*args)
        self.responses = []

    def __call__(self, prompt):
        response = super().__call__(prompt)
        self.responses.append(response)
        _record_invocation_outcome(self, contract="test-scripted-model",
            requested_model=self.model_name, actual_model=self.model_name,
            response_received=bool(response), error_reason="" if response else "empty_response", fallback_used=False)
        return response


@pytest.fixture
def setup(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    database = tmp_path / "business.sqlite3"
    seed_business_fixture(str(database), isolation_root=tmp_path)
    monkeypatch.setattr(chat_tab, "DB_NAME", str(database))
    checkpoint_root = tmp_path / "checkpoints"
    monkeypatch.setattr(task_store, "TASK_STORE_DIR", checkpoint_root)
    revision = workflow_store.save_prepared_workflow(workflow_store.prepare_workflow_save(
        deepcopy(WORKFLOW_ACCEPTANCE_SPEC), workflow_id="ui-scheduled-stock"), root=tmp_path / "workflows")
    scheduler = WorkflowScheduler(root=tmp_path / "schedules", workflow_root=tmp_path / "workflows",
                                  clock=lambda: datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc))
    proposal = scheduler.prepare_schedule_save(revision.workflow_id, revision_id=revision.revision_id,
        parameters={"report_title": "Planlı stok kontrolü"}, interval_seconds=60,
        first_due_at=datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc),
        allowed_scope_bindings={}, budget={"max_steps": 8, "max_replans": 1})
    scheduler.save_prepared_schedule(proposal, confirmed_action_hash=proposal["action_hash"], approved_by="human-schedule-approval")
    # Providers and model lists are unrelated asynchronous UI reads. Pause them
    # here, then drive the actual scheduler/timer adapter explicitly.
    monkeypatch.setattr(chat_tab.AITab, "_refresh_current_source", lambda _self: None)
    widget = chat_tab.AITab()
    timer_was_active = widget._schedule_timer.isActive()
    widget._schedule_timer.stop()
    widget._conversation_state = AgentSessionState(goal="Previous task", status="complete").to_dict()
    widget.composer.clear()
    monkeypatch.setattr("AI.processors.workflow_scheduler.WorkflowScheduler", lambda: scheduler)
    monkeypatch.setattr(widget, "_current_workflow_scope_bindings", lambda: {})
    try:
        yield widget, scheduler, database, checkpoint_root, timer_was_active
    finally:
        widget._chat_worker = None
        widget._action_worker = None
        widget._task_control = None
        widget.close()
        widget.deleteLater()
        assert app is not None


@pytest.mark.parametrize("condition", ["busy", "pending", "paused", "composer", "no_model", "disposing"])
def test_timer_admission_never_claims_while_user_work_or_missing_model_blocks_it(setup, monkeypatch, condition):
    tab, scheduler, database, checkpoint_root, was_active = setup
    selected = {"id": 9, "label": "Cloud", "default_model": "z-ai/glm-5.3-flash"}
    tab.source_combo.setCurrentIndex(tab.source_combo.findData(AI_CHAT_SOURCE_CLOUD_VALUE))
    monkeypatch.setattr(tab, "_selected_provider_record", lambda: selected)
    monkeypatch.setattr(tab, "_worker_is_running", lambda: condition == "busy")
    if condition == "pending":
        state = AgentSessionState.from_dict(tab._conversation_state)
        state.status = "pending_approval"
        state.active_pending_action_id = "current-interactive-action"
        state.pending_actions = [{"action_id": state.active_pending_action_id}]
        tab._conversation_state = state.to_dict()
    elif condition == "paused":
        tab._conversation_state["status"] = "paused"
    elif condition == "composer":
        tab.composer.setPlainText("Önce bu mağazayı incele.")
    elif condition == "no_model":
        selected.clear()
    elif condition == "disposing":
        tab._is_disposing = True
    claim = Mock(wraps=scheduler.claim_due)
    monkeypatch.setattr(scheduler, "claim_due", claim)
    start = Mock()
    monkeypatch.setattr(tab, "_start_scheduled_workflow", start)
    tab._poll_scheduled_workflows()
    claim.assert_not_called()
    start.assert_not_called()
    assert scheduler.list_runs() == [] and was_active


def test_actual_due_poll_creates_one_worker_with_exact_current_selected_cloud_model(setup, monkeypatch):
    tab, scheduler, database, checkpoint_root, was_active = setup
    selected = {"id": 9, "label": "Cloud", "default_model": "z-ai/glm-5.3-flash",
                "provider_code": "openrouter", "_source_kind": "cloud_model", "allow_model_fallback": False}
    tab.source_combo.setCurrentIndex(tab.source_combo.findData(AI_CHAT_SOURCE_CLOUD_VALUE))
    monkeypatch.setattr(tab, "_selected_provider_record", lambda: selected)
    monkeypatch.setattr(tab, "_selected_local_record", lambda: None)
    monkeypatch.setattr(chat_tab, "SyncWorker", DeferredWorker)
    tab._poll_scheduled_workflows()
    worker = tab._chat_worker
    assert worker is not None and worker.isRunning()
    assert worker.func is chat_tab._run_scheduled_chat_with_runtime
    assert worker.kwargs["source"] == AI_CHAT_SOURCE_CLOUD_VALUE
    assert worker.kwargs["runtime_record"] == selected
    assert worker.kwargs["runtime_record"] is not selected
    assert worker.kwargs["lease"].run_id == scheduler.list_runs()[0]["run_id"]
    tab._poll_scheduled_workflows()
    assert tab._chat_worker is worker and len(scheduler.list_runs()) == 1


def test_closed_ai_tab_stops_timer_and_cannot_claim_a_due_schedule(setup, monkeypatch):
    tab, scheduler, database, checkpoint_root, was_active = setup
    claim = Mock(wraps=scheduler.claim_due)
    monkeypatch.setattr(scheduler, "claim_due", claim)
    tab._schedule_timer.start()
    assert tab._schedule_timer.isActive() and was_active
    tab.close()
    assert tab._is_disposing and not tab._schedule_timer.isActive()
    tab._poll_scheduled_workflows()
    claim.assert_not_called()
    assert scheduler.list_runs() == []


def test_selected_cloud_override_runs_real_shared_runtime_and_approval_card_is_bound_to_actual_task(setup, monkeypatch):
    tab, scheduler, database, checkpoint_root, was_active = setup
    selected = {"id": 9, "label": "Cloud", "default_model": "z-ai/glm-5.3-flash", "provider_code": "openrouter",
                "_source_kind": "cloud_model", "reasoning_effort": "low", "allow_model_fallback": False,
                "max_output_tokens": 16000}
    provider_detail = {"id": 9, "label": "Cloud", "default_model": "deepseek/deepseek-v4-flash",
                       "provider_code": "openrouter", "allow_model_fallback": True}
    client = LedgerScriptedClient(scheduler, checkpoint_root, "Planlı stok kontrolü", database.parent / "ui-stock.xlsx")
    client.model_name = "z-ai/glm-5.3-flash"
    client.resource_plan.update({"requested_model": client.model_name, "actual_model": client.model_name})
    built_records = []
    def build(record):
        built_records.append(deepcopy(record))
        return client
    monkeypatch.setattr(chat_tab.ai_actions, "action_get_provider_account", lambda _identity: Result.ok("Current provider", data={"record": provider_detail}))
    monkeypatch.setattr(chat_tab, "build_provider_chat_client", build)
    monkeypatch.setattr(chat_tab, "SyncWorker", DeferredWorker)
    shown = []
    monkeypatch.setattr(tab, "_show_action_approval_dialog", lambda action: shown.append(deepcopy(action)))
    lease = scheduler.claim_due(owner_id="ui-scheduled-worker")[0]
    tab._start_scheduled_workflow(lease, scheduler=scheduler, source=AI_CHAT_SOURCE_CLOUD_VALUE,
                                  runtime_record=selected, allowed_scope_bindings={})
    worker = tab._chat_worker
    kwargs = dict(worker.kwargs)
    kwargs.pop("progress_callback_kw")
    result = worker.func(**kwargs)
    assert result.success, (result.message, result.data)
    assert result.data["runtime"]["resource_plan"] == client.resource_plan
    assert result.data["runtime"]["resource_plan"] is not client.resource_plan
    assert built_records[0]["default_model"] == client.model_name
    assert built_records[0]["reasoning_effort"] == "low" and built_records[0]["allow_model_fallback"] is False
    assert built_records[0]["max_output_tokens"] == 16000
    assert provider_detail["default_model"] == "deepseek/deepseek-v4-flash"
    worker.result_ready.emit(result)
    capture = _capture_turn(tab, prompt="Planlı stok kontrolü", review_previous={}, capture={"turn_result": result},
        started_at="2026-10-11T09:00:00+00:00", completed_at="2026-10-11T09:00:01+00:00", duration_seconds=1)
    assert capture["runtime"]["model_response_count"] == sum(bool(response) for response in client.responses)
    assert capture["runtime"]["model_response_count"] > 0
    assert capture["runtime"]["actual_model"] == client.model_name
    assert capture["runtime"]["any_model_fallback_used"] is False
    assert len(shown) == 1
    action = shown[0]
    actual_id = scheduler.list_runs()[0]["session_id"]
    assert action["_agent_task_session_id"] == actual_id == tab._conversation_state["session_id"]
    assert actual_id != scheduler.list_runs()[0]["receipt"]["submission_session_id"]
    assert action["_agent_task_runtime"]["model_name"] == client.model_name
    assert task_store.load_agent_task_state(actual_id, root=checkpoint_root).status == "pending_approval"
    assert not client.output.exists()
    assert tab._conversation_state["active_pending_action_id"] == action["action_id"]
    worker.running = False
    worker.finished.emit()
    assert tab._chat_worker is None and tab._task_control is None
    tab._poll_scheduled_workflows()
    assert len(scheduler.list_runs()) == 1
    approved = chat_tab._run_approved_chat_action(action)
    assert approved.success, (approved.message, approved.data)
    assert approved.data["session_state"]["session_id"] == actual_id
    assert approved.data["session_state"]["status"] == "complete"
    assert approved.data["execute"]["verify"]["verified_by"] == "xlsx_exact_snapshot_readback"
    assert client.output.is_file()
    assert built_records[-1]["default_model"] == client.model_name
    assert built_records[-1]["allow_model_fallback"] is False
    reconciled = scheduler.reconcile_run(lease.run_id, session_loader=task_store.load_agent_task_state)
    assert reconciled["status"] == "completed" and reconciled["session_id"] == actual_id
