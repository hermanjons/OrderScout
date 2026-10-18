"""Live driver proof checks using canonical runtime and durable child records."""
from copy import deepcopy
import ast
from pathlib import Path

import pytest

from AI.processors.business_agent_acceptance_cli import ObservedCloudClient, SCENARIOS, _source_snapshot, retain_approved_export, acceptance_provider_endpoint
from AI.processors.business_child_acceptance import validate_child_stock_report, validate_child_stock_cells
from AI.processors.session_state import AgentSessionState
from AI.processors.task_store import load_agent_task_state, save_agent_task_state
from AI.processors.turn_service import run_typed_control_turn
from tests.domain_ai.test_child_task_runtime import Model, _delegate, _read, _run, database


@pytest.fixture
def prepared(database, tmp_path):
    ledger = []
    parent_plan = {"steps": [_delegate(),
        {"id": "import_child", "operation_id": "artifacts.read", "depends_on": ["delegated"],
         "arguments": {"artifact_id": {"$from_step": "delegated", "path": "tool_result.artifact_refs[0].artifact_id"}},
         "expected_evidence": ["result", "artifact"]},
        {"id": "report", "operation_id": "reports.build_snapshot", "depends_on": ["import_child"],
         "arguments": {"title": "Independent child stock report", "sources": [{"source_id": "stock", "source_step_id": "import_child",
            "operation_id": "artifacts.read", "result": {"$from_step": "import_child", "path": "tool_result"}}],
            "sheets": [
                {"name": "Döviz", "source_id": "stock", "rows_path": "result.stock_value_by_currency", "columns": [
                    {"key": "currency", "label": "Döviz", "source_path": "currency", "data_type": "string"},
                    {"key": "amount", "label": "Değer", "source_path": "amount", "data_type": "number"}]},
                {"name": "Miktar", "source_id": "stock", "rows_path": "result.top_balances", "columns": [
                    {"key": "sku", "label": "SKU", "source_path": "sku", "data_type": "string"},
                    {"key": "quantity", "label": "Miktar", "source_path": "balance", "data_type": "number"},
                    {"key": "unit", "label": "Birim", "source_path": "unit", "data_type": "string"}]}]},
         "expected_evidence": ["report_snapshot"]},
        {"id": "prepare", "operation_id": "reports.xlsx.prepare", "depends_on": ["report"],
         "arguments": {"report_snapshot": {"$from_step": "report", "path": "tool_result.report_snapshot"},
                       "output_path": str(tmp_path / "child-stock.xlsx")}, "expected_evidence": ["action"]}]}
    selected = Model(parent_plan, _read())
    selected.model_name = "fixture-model"
    model = ObservedCloudClient(selected, ledger.append)
    started = _run(database, model, persist=True, task_store_root=str(tmp_path / "tasks"))
    state = started.data["state"]
    assert state["status"] == "pending_approval", state["active_entities"].get("task_plan")
    turn = {"scenario_id": "child_stock_report_prepare", "raw_turn_data": started.data,
            "model_responses": ledger, "pending_action": state["pending_actions"][0],
            "runtime": {"requested_model": "fixture-model", "actual_model": "fixture-model"}}
    fixture = {"stock": {"stock_value_by_currency": {"TRY": 400, "USD": 30},
                         "balance_by_sku": {"PILOT-KUPA": 4, "PILOT-FILTRE": 3, "PILOT-BOS": 0}}}
    return turn, fixture


def _verify(turn, fixture, tmp_path):
    return validate_child_stock_report(turn, fixture, isolation_root=tmp_path, task_store_root=tmp_path / "tasks")


def test_real_same_client_child_plan_durable_read_parent_import_report_and_retained_workbook(prepared, database, tmp_path):
    turn, fixture = prepared
    evidence = _verify(turn, fixture, tmp_path)
    assert evidence["passed"], evidence
    proof = evidence["proof"][0]
    child_calls = [row for row in turn["model_responses"] if row.get("delegated_child")]
    assert child_calls and {row["delegated_child"]["task_id"] for row in child_calls} == {proof["child_task_id"]}
    assert len({row["invocation"] for row in turn["model_responses"]}) == len(turn["model_responses"])
    approved = run_typed_control_turn("Onaylıyorum.", mode="approve", session_state=turn["raw_turn_data"]["state"],
                                      client=None, db_name=str(database), allow_approval_execute=True)
    assert approved.success
    saved_turn = {"scenario_id": "child_stock_report_approve", "approved_action": turn["pending_action"],
                  "execute": {"success": True, "data": approved.data}}
    retained = retain_approved_export(saved_turn, isolation_root=tmp_path, artifact_path=tmp_path / "campaign.json")
    assert retained["byte_count"] > 0 and validate_child_stock_cells(retained, fixture)["passed"]


@pytest.mark.parametrize("mutation", ["receipt", "origin", "hash", "freshness", "ledger", "ledger_model", "reservation", "quantity", "currency"])
def test_claimed_child_success_wrong_source_or_native_cells_cannot_pass(prepared, tmp_path, mutation):
    original, fixture = prepared
    turn = deepcopy(original)
    state = turn["raw_turn_data"]["state"]
    steps = state["completed_steps"]
    if mutation == "receipt":
        steps[0]["result_data"]["tool_result"]["business_observations_in_receipt"] = True
    elif mutation == "origin":
        steps[1]["result_data"]["tool_result"]["artifact"]["origin"]["task_id"] = state["session_id"]
    elif mutation == "hash":
        steps[1]["result_data"]["tool_result"]["artifact"]["result_hash"] = "0" * 64
    elif mutation == "freshness":
        steps[1]["result_data"]["tool_result"]["fresh_read"] = True
    elif mutation == "ledger":
        turn["model_responses"] = [row for row in turn["model_responses"] if not row.get("delegated_child")]
    elif mutation == "ledger_model":
        for row in turn["model_responses"]:
            if row.get("delegated_child"):
                row["actual_model"] = "different-model"
    elif mutation == "reservation":
        state["active_entities"]["execution_budget"]["started_steps"] -= 1
    else:
        snapshot = turn["pending_action"]["arguments"]["payload"]["report_snapshot"]
        sheet = next(sheet for sheet in snapshot["sheets"] if sheet["name"] == ("Miktar" if mutation == "quantity" else "Döviz"))
        sheet["rows"][0][1] = str(sheet["rows"][0][1])
    assert not _verify(turn, fixture, tmp_path)["passed"]


@pytest.mark.parametrize("mutation", ["pending", "failed", "depth", "scope", "budget", "duplicate", "boolean", "unit"])
def test_oracle_reopens_actual_durable_child_instead_of_accepting_parent_receipt(prepared, tmp_path, mutation):
    turn, fixture = prepared
    child_id = turn["raw_turn_data"]["state"]["completed_steps"][0]["result_data"]["tool_result"]["child_task_id"]
    child = load_agent_task_state(child_id, root=tmp_path / "tasks")
    if mutation == "pending":
        child.pending_actions = [{"action_id": "invented", "approval_required": True}]
    elif mutation == "failed":
        child.status = "failed"
    elif mutation == "depth":
        child.active_entities["child_delegation_policy"]["depth"] = 2
    elif mutation == "scope":
        child.active_entities["child_delegation_policy"]["parent_task_id"] = "otherparent"
    elif mutation == "budget":
        child.active_entities["execution_budget"]["max_steps"] += 1
    else:
        actual = child.completed_steps[0].result_data["tool_result"]
        if mutation == "duplicate":
            actual["stock_value_by_currency"].append(deepcopy(actual["stock_value_by_currency"][0]))
        elif mutation == "boolean":
            next(row for row in actual["top_balances"] if row["sku"] == "PILOT-BOS")["balance"] = False
        else:
            actual["top_balances"][0]["unit"] = "kg"
    save_agent_task_state(child, root=tmp_path / "tasks")
    evidence = _verify(turn, fixture, tmp_path)
    assert not evidence["passed"]
    if mutation in {"duplicate", "boolean", "unit"}:
        assert "durable_child_stock_not_independent_fixture" in evidence["problems"]


def test_driver_declares_real_child_chain_and_fingerprints_its_evidence_sources():
    assert SCENARIOS["child_stock_report_prepare"]["required_operations"] == ["agent.delegate", "artifacts.read", "reports.build_snapshot", "reports.xlsx.prepare"]
    assert SCENARIOS["child_stock_report_followup"]["required_goal_complete"] is True
    snapshot = _source_snapshot()
    assert not snapshot["missing_requested_sources"]
    files = {row["path"] for row in snapshot["files"]}
    assert {"AI/processors/child_task_runtime.py", "AI/processors/business_child_acceptance.py",
            "tests/domain_ai/test_business_child_acceptance.py", "tests/support/run_isolated_ai_checks.py"}.issubset(files)


def test_driver_endpoint_defaults_follow_the_actual_provider_owner_without_hardcoded_host(monkeypatch):
    from AI.processors import cloud_runtime, business_agent_acceptance_cli
    monkeypatch.setitem(cloud_runtime.DEFAULT_BASE_URLS, "openrouter", "https://canonical-owner.invalid/v1")
    assert acceptance_provider_endpoint({"provider_code": "openrouter"}) == "https://canonical-owner.invalid/v1"
    for provider in ("openai", "anthropic", "gemini"):
        assert acceptance_provider_endpoint({"provider_code": provider}) == cloud_runtime.DEFAULT_BASE_URLS[provider]
    assert acceptance_provider_endpoint({"provider_code": "custom", "endpoint_url": "https://selected-provider.invalid/v1"}) == "https://selected-provider.invalid/v1"
    with pytest.raises(ValueError):
        acceptance_provider_endpoint({"provider_code": "custom"})
    source = Path(business_agent_acceptance_cli.__file__).read_text(encoding="utf-8")
    literals = [node.value for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert not any(value.startswith("https://") for value in literals)
