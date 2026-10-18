"""A saved recipe runs the shared model graph with fresh real SQLite reads.

The structured model responses are fixtures; business observations, dependency
binding, approval, XLSX writing and independent cell reads are production paths.
"""
from copy import deepcopy
import json

from openpyxl import load_workbook
from sqlmodel import Session

from AI.processors import tools, workflow_store
from AI.processors.business_acceptance_fixtures import WORKFLOW_ACCEPTANCE_SPEC, seed_business_fixture
from AI.processors.session_state import AgentSessionState
from AI.processors.task_runtime import run_agent_task
from AI.processors.turn_service import run_typed_control_turn
from Core.utils.model_utils import get_engine
from Stock.constants.domain_constants import StockTxDirection, StockTxReason
from Stock.models.models import StockTx


def test_saved_instructions_replan_fresh_stock_each_run_and_require_new_exact_report_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", tmp_path / "ai")
    database = tmp_path / "business.sqlite3"
    seed_business_fixture(str(database), isolation_root=tmp_path)
    prepared = tools.workflows_prepare_save(spec=deepcopy(WORKFLOW_ACCEPTANCE_SPEC), workflow_id="repeat-stock")
    state = AgentSessionState(goal="Kaydet", active_domain="general", status="pending_approval")
    state.add_pending_action(prepared.data["action"])
    saved = run_typed_control_turn("Onaylıyorum.", mode="approve", session_state=state, client=None,
                                  db_name=str(database), allow_approval_execute=True)
    assert saved.success, saved.message
    previous = saved.data["state"]
    all_prompts = []
    action_ids = []

    for iteration, expected_balance, expected_try_value in ((1, 4, 400), (2, 6, 600)):
        if iteration == 2:
            with Session(get_engine(str(database))) as session:
                session.add(StockTx(item_id=401, warehouse_id=301, direction=StockTxDirection.IN_,
                    reason=StockTxReason.manual_in, qty=2, unit_cost=100, currency="TRY",
                    unit_cost_input_mode="gross", company_id=201))
                session.commit()
        title = "Tekrar " + str(iteration)
        output = tmp_path / ("current-stock-" + str(iteration) + ".xlsx")
        columns = [{"key": key, "label": label, "source_path": key, "data_type": kind}
                   for key, label, kind in (("sku", "SKU", "string"), ("balance", "Miktar", "number"),
                                           ("unit", "Birim", "string"), ("stock_value", "Değer", "number"),
                                           ("stock_value_currency", "Döviz", "string"))]
        plan = {"steps": [
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

        def planner(prompt):
            all_prompts.append(prompt)
            if prompt.startswith("OrderScout semantic action verifier"):
                return json.dumps({"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
                                   "unwanted_effect": False, "reason": "The current workflow asks for this exact report proposal"})
            if prompt.startswith("GoalPlan observation"):
                return json.dumps({"decision": "continue", "reason": "Continue the pending report graph"})
            return json.dumps(plan)

        def shared_runner(goal, **options):
            return run_agent_task(goal, **options, turn_interpretation={
                "mode": "act", "domain": "general", "intent_kind": "action", "valid": True,
                "objective": goal, "requested_fields": ["artifact"], "requires_clarification": False})

        started = workflow_store.run_workflow("repeat-stock", parameters={"report_title": title},
            current_session=previous, planner_client=planner, runner=shared_runner,
            runner_options={"domain": "general", "db_name": str(database), "persist": False, "max_steps": 8})
        assert started.success, started.message
        current = started.data["state"]
        assert current["status"] == "pending_approval", current["active_entities"].get("goal_progress")
        assert current["session_id"] != previous["session_id"]
        assert [step["tool_names"] for step in current["completed_steps"]] == [
            ["stock.inventory_overview"], ["reports.build_snapshot"], ["reports.xlsx.prepare"]]
        invocation = current["active_entities"]["workflow_invocation"]
        assert invocation["requires_current_sources"] is True and invocation["requires_current_approval"] is True
        observed = current["completed_steps"][0]["result_data"]["tool_result"]
        kupa = next(row for row in observed["top_balances"] if row["sku"] == "PILOT-KUPA")
        assert kupa["balance"] == expected_balance and kupa["stock_value"] == expected_try_value
        assert {row["currency"]: row["amount"] for row in observed["stock_value_by_currency"]} == {"TRY": expected_try_value, "USD": 30}
        assert not output.exists()
        action_ids.append(current["active_pending_action_id"])
        approved = run_typed_control_turn("Onaylıyorum.", mode="approve", session_state=current, client=None,
                                          db_name=str(database), allow_approval_execute=True)
        assert approved.success, approved.message
        assert approved.data["execute"]["verify"]["verified_by"] == "xlsx_exact_snapshot_readback"
        workbook = load_workbook(output, read_only=True, data_only=False)
        try:
            rows = list(workbook["Stok"].values)
            assert ("PILOT-KUPA", expected_balance, "adet", expected_try_value, "TRY") in rows
            assert ("PILOT-FILTRE", 3, "adet", 30, "USD") in rows
        finally:
            workbook.close()
        previous = approved.data["state"]
    assert len(set(action_ids)) == 2
    assert sum(prompt.startswith("Sen OrderScout") or '"steps"' in prompt for prompt in all_prompts) >= 2
