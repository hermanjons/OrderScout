"""Scheduled work uses the real shared turn, tools, checkpoint and XLSX paths.

Only model JSON/text is scripted. No business tool, task runtime, builder,
approval executor, or checkpoint reader is substituted.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from openpyxl import load_workbook
from sqlmodel import Session

from AI.processors import task_store, tools, workflow_store
from AI.processors.business_acceptance_fixtures import WORKFLOW_ACCEPTANCE_SPEC, seed_business_fixture
from AI.processors.conversation_runtime import run_contextual_conversation_turn
from AI.processors.scheduled_task_runtime import run_scheduled_task
from AI.processors.session_state import AgentSessionState
from AI.processors.workflow_scheduler import WorkflowScheduler
from Core.utils.model_utils import get_engine
from Stock.constants.domain_constants import StockTxDirection, StockTxReason
from Stock.models.models import StockTx


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


def _plan(title, output):
    columns = [{"key": key, "label": label, "source_path": key, "data_type": kind}
               for key, label, kind in (("sku", "SKU", "string"), ("balance", "Miktar", "number"),
                                       ("unit", "Birim", "string"), ("stock_value", "Değer", "number"),
                                       ("stock_value_currency", "Döviz", "string"))]
    return {"steps": [
        {"id": "current_stock", "operation_id": "stock.inventory_overview", "arguments": {"limit": 50},
         "depends_on": [], "objective": "Read current stock", "expected_evidence": ["top_balances", "stock_value_by_currency"]},
        {"id": "current_report", "operation_id": "reports.build_snapshot", "depends_on": ["current_stock"],
         "objective": "Build this invocation's exact observed report", "expected_evidence": ["report_snapshot", "source_receipts"],
         "arguments": {"title": title, "sources": [{"source_id": "stock", "source_step_id": "current_stock",
             "operation_id": "stock.inventory_overview", "result": {"$from_step": "current_stock", "path": "tool_result"}}],
             "sheets": [{"name": "Stok", "source_id": "stock", "rows_path": "top_balances", "columns": columns}]}},
        {"id": "current_prepare", "operation_id": "reports.xlsx.prepare", "depends_on": ["current_report"],
         "objective": "Ask for the exact current file creation approval", "expected_evidence": ["action", "content_hash"],
         "arguments": {"report_snapshot": {"$from_step": "current_report", "path": "tool_result.report_snapshot"}, "output_path": str(output)}},
    ]}


class ScriptedClient:
    model_name = "deepseek/deepseek-v4.1-flash"
    turn_timeout_seconds = 180

    def __init__(self, scheduler, checkpoint_root, title, output):
        self.scheduler, self.checkpoint_root = scheduler, checkpoint_root
        self.title, self.output = title, output
        self.calls, self.bound_before_plan, self.budgets = [], [], []
        self.resource_plan = {"provider_code": "openrouter", "requested_model": self.model_name,
                              "actual_model": self.model_name, "fallback_used": False}

    def reserve_task_budget(self, *, max_steps):
        self.budgets.append(max_steps)

    def __call__(self, prompt):
        self.calls.append(prompt)
        if prompt.startswith("OrderScout typed tur yorumu"):
            return json.dumps({"mode": "act", "domain": "general", "intent_kind": "action",
                               "objective": "Güncel stok için Excel raporunu hazırla ve kaydetmeden onayıma sun.",
                               "requested_fields": ["artifact"], "requires_clarification": False,
                               "reason": "The saved user workflow explicitly requests a current stock report", "clarification": ""})
        if prompt.startswith("OrderScout semantic action verifier"):
            return json.dumps({"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
                               "unwanted_effect": False, "reason": "Exact current report requested by the workflow"})
        if prompt.startswith("GoalPlan observation"):
            return json.dumps({"decision": "continue", "reason": "Continue the pending source-bound report graph"})
        if "agent task final cevabi yaz." in prompt:
            return ""
        run = self.scheduler.list_runs()[0]
        assert run["status"] == "running" and run["session_id"]
        actual = task_store.load_agent_task_state(run["session_id"], root=self.checkpoint_root)
        assert actual.active_entities["task_checkpoint"]["phase"] == "initialized"
        assert actual.active_entities["planning_not_started"] is True
        assert actual.completed_steps == []
        assert actual.session_id != run["receipt"]["submission_session_id"]
        self.bound_before_plan.append(actual.session_id)
        return json.dumps(_plan(self.title, self.output))


def test_actual_scheduled_shared_runtime_reads_fresh_stock_and_requires_current_file_approval_each_time(tmp_path, monkeypatch):
    database = tmp_path / "business.sqlite3"
    seed_business_fixture(str(database), isolation_root=tmp_path)
    workflow_root, checkpoint_root = tmp_path / "workflows", tmp_path / "checkpoints"
    unrelated_default_root = tmp_path / "unrelated-default-checkpoints"
    monkeypatch.setattr(task_store, "TASK_STORE_DIR", unrelated_default_root)
    revision = workflow_store.save_prepared_workflow(workflow_store.prepare_workflow_save(
        deepcopy(WORKFLOW_ACCEPTANCE_SPEC), workflow_id="scheduled-stock"), root=workflow_root)
    clock = Clock()
    scheduler = WorkflowScheduler(root=tmp_path / "schedules", workflow_root=workflow_root, clock=clock, lease_seconds=300)
    proposal = scheduler.prepare_schedule_save(revision.workflow_id, revision_id=revision.revision_id,
        parameters={"report_title": "Planlı stok kontrolü"}, interval_seconds=60, first_due_at=clock(),
        allowed_scope_bindings={}, budget={"max_steps": 8, "max_replans": 1})
    scheduler.save_prepared_schedule(proposal, confirmed_action_hash=proposal["action_hash"], approved_by="human-schedule-approval")
    previous = AgentSessionState(goal="Previous completed task", status="complete")
    previous.action_history = [{"approved_by": "old-approval-do-not-copy"}]
    action_ids, task_ids = [], []
    client = ScriptedClient(scheduler, checkpoint_root, "Planlı stok kontrolü", tmp_path / "stock-1.xlsx")

    for iteration, expected_quantity, expected_value in ((1, 4, 400), (2, 6, 600)):
        if iteration == 2:
            with Session(get_engine(str(database))) as session:
                session.add(StockTx(item_id=401, warehouse_id=301, direction=StockTxDirection.IN_,
                    reason=StockTxReason.manual_in, qty=2, unit_cost=100, currency="TRY",
                    unit_cost_input_mode="gross", company_id=201))
                session.commit()
            clock.advance(60)
            client.output = tmp_path / "stock-2.xlsx"
        lease = scheduler.claim_due(owner_id="actual-shared-runtime")[0]
        result = run_scheduled_task(lease, scheduler=scheduler, client=client, provider_code="openrouter",
            model_name=client.model_name, db_name=str(database), current_session=previous,
            allowed_scope_bindings={}, task_store_root=str(checkpoint_root),
            runtime_context={"source": "cloud", "provider_id": 9, "model_name": client.model_name})
        assert result.success, (result.message, result.data)
        run = result.data["run"]
        current = result.data["workflow_result"]["session_state"]
        assert current["status"] == "pending_approval" and run["status"] == "awaiting_approval"
        assert current["session_id"] == run["session_id"] == client.bound_before_plan[-1]
        assert current["session_id"] != run["receipt"]["submission_session_id"]
        assert current["session_id"] != previous.session_id
        task_ids.append(current["session_id"])
        assert task_store.load_agent_task_state(current["session_id"], root=checkpoint_root).status == "pending_approval"
        budget = current["active_entities"]["execution_budget"]
        assert (budget["max_steps"], budget["max_replans"], budget["started_steps"]) == (8, 1, 3)
        metadata = current["active_entities"]["runtime_context"]
        assert metadata["provider_id"] == 9 and metadata["model_name"] == client.model_name
        assert "old-approval-do-not-copy" not in json.dumps(current)
        assert [step["tool_names"] for step in current["completed_steps"]] == [
            ["stock.inventory_overview"], ["reports.build_snapshot"], ["reports.xlsx.prepare"]]
        actual_stock = current["completed_steps"][0]["result_data"]["tool_result"]
        item = next(row for row in actual_stock["top_balances"] if row["sku"] == "PILOT-KUPA")
        assert item["balance"] == expected_quantity and item["stock_value"] == expected_value
        assert {row["currency"]: row["amount"] for row in actual_stock["stock_value_by_currency"]} == {"TRY": expected_value, "USD": 30}
        assert not client.output.exists()
        action_ids.append(current["active_pending_action_id"])
        assert scheduler.claim_due(owner_id="duplicate-attempt") == []
        calls_before_control = len(client.calls)
        blocked = run_contextual_conversation_turn("Onaylıyorum.", client=client, provider_code="openrouter",
            model_name=client.model_name, db_name=str(database), history=[], session_state=current,
            persist=True, task_store_root=str(checkpoint_root), allow_approval_execute=False)
        assert not client.output.exists() and blocked["session_state"]["active_pending_action_id"] == action_ids[-1]
        assert len(client.calls) == calls_before_control
        approved = run_contextual_conversation_turn("Onaylıyorum.", client=client, provider_code="openrouter",
            model_name=client.model_name, db_name=str(database), history=[], session_state=blocked["session_state"],
            persist=True, task_store_root=str(checkpoint_root), allow_approval_execute=True)
        assert approved["success"], approved["answer"]
        assert approved["session_state"]["status"] == "complete"
        execution = next(row for row in approved["tool_results"] if row["tool"] == "execute_approved_operation")
        assert execution["data"]["verify"]["verified_by"] == "xlsx_exact_snapshot_readback"
        workbook = load_workbook(client.output, read_only=True, data_only=False)
        try:
            rows = list(workbook["Stok"].values)
            assert ("PILOT-KUPA", expected_quantity, "adet", expected_value, "TRY") in rows
            assert ("PILOT-FILTRE", 3, "adet", 30, "USD") in rows
        finally:
            workbook.close()
        reconciled = scheduler.reconcile_run(lease.run_id, session_loader=lambda identity: task_store.load_agent_task_state(identity, root=checkpoint_root))
        assert reconciled["status"] == "completed" and reconciled["session_id"] == current["session_id"]
        assert scheduler.list_schedules()[0]["active_run_id"] is None
        previous = AgentSessionState.from_dict(approved["session_state"])
    assert len(set(task_ids)) == 2 and len(set(action_ids)) == 2
    assert client.budgets.count(8) == 2 and all(1 <= count <= 8 for count in client.budgets)
    assert len(client.bound_before_plan) == 2
    assert not unrelated_default_root.exists()
