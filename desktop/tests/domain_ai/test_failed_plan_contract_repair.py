"""Replay the real GLM date/ID failure with canonical SQLite reads.

Only model responses are scripted. The Oct 11 fixture and explicit current
dates keep the captured failure reproducible independently of the wall clock.
Business handlers, catalog guards, checkpoints and execution budgets are real.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from AI.processors import task_runtime, task_store
from AI.processors.business_acceptance_fixtures import seed_business_fixture
from AI.processors.observation_projection import source_projection_hash


CURRENT_START, CURRENT_END = "2026-10-05", "2026-10-11"
PRIOR_START, PRIOR_END = "2026-09-28", "2026-10-04"


def _step(identity, operation, arguments, dependencies, objective, evidence):
    return {"id": identity, "operation_id": operation, "arguments_json": json.dumps(arguments),
            "depends_on": dependencies, "objective": objective, "expected_evidence": evidence}


def _captured_failure_plan():
    return {"steps": [
        _step("step_1", "orders.summary", {"period": "last_7_days", "start_date": CURRENT_START, "end_date": CURRENT_END}, [],
              "Read Pilot Ana current sales", ["total_orders", "estimated_revenue", "start_ms", "end_ms"]),
        _step("step_2", "orders.summary", {
            "start_date": {"$from_step": "step_1", "path": "tool_result.start_ms"},
            "end_date": {"$from_step": "step_1", "path": "tool_result.end_ms"}}, ["step_1"],
              "Read Pilot Ana previous sales", ["total_orders", "estimated_revenue", "start_ms", "end_ms"]),
    ]}


def _captured_wrong_replacement():
    # Actual candidate-2 response: correct YYYY-MM-DD values, but the failed
    # step_2 identity is reused despite its claim to supply a new unique ID.
    return {"steps": [_step("step_2", "orders.summary", {
        "api_account_ids": [101], "start_date": PRIOR_START, "end_date": PRIOR_END}, ["step_1"],
        "Onceki es sureli 7 gunu ayri acik tarih okumasiyla oku; last_14_days kullanma.",
        ["total_orders", "cancelled_orders", "revenue_by_currency", "currency", "currencies", "start_ms", "end_ms", "source_snapshot_hash"])],
        "reason": "Date argument types corrected, but captured failed ID is still reused."}


def _fresh_replacement():
    replacement = _captured_wrong_replacement()
    replacement["steps"][0]["id"] = "prior_sales_repaired"
    replacement["reason"] = "Use a fresh step identity and observed current bounds to read the adjacent prior period."
    return replacement


class ScriptedRepairClient:
    """One wired client records the actual provider-adapter transport choice."""
    model_name = "z-ai/glm-5.3-flash"

    def __init__(self, root, repair):
        self.root, self.repair = root, repair
        self.calls, self.reservations = [], []
        self.session_id = None
        self.original_current = None
        self.deadline = object()
        self.resource_plan = {"provider_code": "openrouter", "requested_model": self.model_name,
                              "actual_model": self.model_name, "fallback_used": False,
                              "capability_profile": {"structured_output_runtime_enabled": True,
                                                     "native_tool_runtime_enabled": False,
                                                     "prepare_write_allowed": True}}

    def created(self, state):
        self.session_id = state.session_id

    def reserve_task_budget(self, *, max_steps):
        self.reservations.append((max_steps, id(self), self.deadline))

    def invoke_structured(self, prompt, *, schema):
        return self._reply(prompt, "structured", schema)

    def invoke_json_text(self, prompt, *, schema):
        assert "GUARDED JSON RESPONSE CONTRACT (authoritative)" in prompt
        return self._reply(prompt, "guarded_json", schema)

    def __call__(self, prompt):
        if "agent task final cevabi yaz." in prompt:
            self.calls.append({"kind": "final_answer", "transport": "text", "client_id": id(self),
                               "deadline": self.deadline, "schema": None, "prompt": prompt})
            return "Current period: 3 orders and 3000 TRY. Prior period: 2 orders and 800 TRY."
        return self._reply(prompt, "text", None)

    def _reply(self, prompt, transport, schema):
        if prompt.startswith("Failed-step recovery plan contract repair."):
            kind = "contract_repair"
            assert "step_id:already_executed" in prompt
            assert '"operation_id": "orders.summary"' in prompt
            assert "arguments.start_date:type" in prompt and "arguments.end_date:type" in prompt
            response = self.repair
        elif "yeniden planla." in prompt and "Exact failure diagnostics:" in prompt:
            kind = "replan"
            actual = task_store.load_agent_task_state(self.session_id, root=self.root)
            self.original_current = deepcopy(actual.completed_steps[0].to_dict())
            assert actual.completed_steps[1].status == "failed"
            assert actual.completed_steps[1].result_data["argument_problems"] == ["arguments.start_date:type", "arguments.end_date:type"]
            response = _captured_wrong_replacement()
        elif prompt.startswith("GoalPlan observation"):
            kind = "observation"
            actual = task_store.load_agent_task_state(self.session_id, root=self.root)
            finished = actual.completed_steps[-1].step_id == "prior_sales_repaired"
            if finished:
                observed = [row.result_data["tool_result"] for row in actual.completed_steps if row.status == "completed"]
                assert [(row["total_orders"], row["estimated_revenue"]) for row in observed] == [(3, 3000), (2, 800)]
            response = {"decision": "complete" if finished else "continue",
                        "reason": "Both requested periods observed" if finished else "Keep exact remaining read graph", "steps": []}
        elif "domain agent task plani olustur." in prompt:
            kind = "initial_plan"
            response = _captured_failure_plan()
        else:
            raise AssertionError(f"Unexpected model phase: {prompt[:100]}")
        self.calls.append({"kind": kind, "transport": transport, "client_id": id(self),
                           "deadline": self.deadline, "schema": schema, "prompt": prompt})
        return response if isinstance(response, str) else json.dumps(response)


def _run(tmp_path, repair, *, max_steps=3):
    db = str(tmp_path / "business.sqlite3")
    seed_business_fixture(db, isolation_root=tmp_path,
                          now=datetime(2026, 10, 11, 12, tzinfo=timezone(timedelta(hours=3))))
    root = tmp_path / "checkpoints"
    client = ScriptedRepairClient(root, repair)
    result = task_runtime.run_agent_task(
        "Read Pilot Ana sales for 2026-10-05..2026-10-11 and 2026-09-28..2026-10-04 separately, with their observed order counts and TRY amounts.",
        domain="general", planner_client=client, chat_client=client, db_name=db,
        max_steps=max_steps, max_replans=1, persist=True, task_store_root=str(root),
        task_created_callback=client.created,
        turn_interpretation={"mode": "inspect", "intent_kind": "data_read", "domain": "general", "valid": True,
                             "objective": "Read exact current and prior Pilot Ana sales separately",
                             "requested_fields": [], "requires_clarification": False},
    )
    return result.data["state"], client


def _assert_no_effects(state, tmp_path):
    assert state["pending_actions"] == [] and state["action_history"] == []
    assert not list(tmp_path.rglob("*.xlsx"))
    assert not any(row["operation_name"] == "reports.build_snapshot" for row in state["observations"])


def test_captured_failed_date_binding_and_reused_id_repair_reads_actual_prior_period_once(tmp_path):
    state, client = _run(tmp_path, _fresh_replacement())
    assert state["status"] == "complete", state
    assert [(row["step_id"], row["status"]) for row in state["completed_steps"]] == [
        ("step_1", "completed"), ("step_2", "failed"), ("prior_sales_repaired", "completed")]
    current, failed, prior = state["completed_steps"]
    assert current == client.original_current
    assert current["result_data"]["tool_result"]["total_orders"] == 3
    assert current["result_data"]["tool_result"]["estimated_revenue"] == 3000
    assert prior["result_data"]["tool_result"]["total_orders"] == 2
    assert prior["result_data"]["tool_result"]["estimated_revenue"] == 800
    assert failed["result_data"]["argument_problems"] == ["arguments.start_date:type", "arguments.end_date:type"]
    assert failed["verification_status"] == "superseded" and not failed["tool_names"]
    for step in (current, prior):
        payload = step["result_data"]["tool_result"]
        assert payload["currency"] == "TRY" and payload["revenue_by_currency"] == {"TRY": payload["estimated_revenue"]}
        assert payload["account_scopes"][0]["api_account_id"] == 101 and payload["account_scopes"][0]["environment"] == "stage"
        assert len(payload["account_scopes"]) == 1
    current_payload, prior_payload = current["result_data"]["tool_result"], prior["result_data"]["tool_result"]
    assert current_payload["start_ms"] == prior_payload["end_ms"] + 1
    assert current_payload["end_ms"] - current_payload["start_ms"] == prior_payload["end_ms"] - prior_payload["start_ms"]
    assert source_projection_hash(current_payload) == source_projection_hash(client.original_current["result_data"]["tool_result"])
    assert state["active_entities"]["execution_budget"]["started_steps"] == 3
    assert state["active_entities"]["execution_budget"]["applied_replans"] == 1
    replan = state["active_entities"]["replans"][0]
    assert replan["contract_repair"]["invoked"] and replan["contract_repair"]["applied"]
    assert replan["contract_repair"]["initial_raw_step_ids"] == ["step_2"]
    assert replan["accepted_step_ids"] == ["prior_sales_repaired"]
    repairs = [row for row in client.calls if row["kind"] == "contract_repair"]
    assert len(repairs) == 1 and repairs[0]["transport"] == "guarded_json"
    assert len([row for row in client.calls if row["kind"] == "replan"]) == 1
    assert len([row for row in client.calls if row["kind"] == "initial_plan"]) == 1
    assert len([row for row in client.calls if row["kind"] == "observation"]) == 2
    assert len([row for row in client.calls if row["kind"] == "final_answer"]) <= 1
    assert len(client.calls) <= 6
    assert all(row["client_id"] == id(client) and row["deadline"] is client.deadline for row in client.calls)
    assert all(row[2] is client.deadline for row in client.reservations)
    persisted = task_store.load_agent_task_state(state["session_id"], root=client.root)
    assert persisted.status == "complete" and persisted.completed_steps[0].to_dict() == client.original_current
    _assert_no_effects(state, tmp_path)


@pytest.mark.parametrize("repair", [_captured_wrong_replacement(), "malformed JSON body"])
def test_repair_is_bounded_and_repeated_failed_id_or_malformed_json_stays_blocked(tmp_path, repair):
    state, client = _run(tmp_path, repair)
    assert state["status"] == "failed"
    assert len(state["completed_steps"]) == 2 and state["active_entities"]["execution_budget"]["started_steps"] == 2
    assert state["completed_steps"][0] == client.original_current
    assert state["active_entities"]["execution_budget"]["applied_replans"] == 0
    assert len([row for row in client.calls if row["kind"] == "replan"]) == 1
    assert len([row for row in client.calls if row["kind"] == "contract_repair"]) == 1
    assert len(client.calls) == 4
    assert len(state["active_entities"]["replans"]) == 1
    assert state["active_entities"]["replans"][0]["applied"] is False
    _assert_no_effects(state, tmp_path)


def test_zero_remaining_step_budget_performs_no_replan_or_repair_provider_invocation(tmp_path):
    state, client = _run(tmp_path, _fresh_replacement(), max_steps=2)
    assert state["status"] == "failed" and state["active_entities"]["execution_budget"]["started_steps"] == 2
    assert not any(row["kind"] in {"replan", "contract_repair"} for row in client.calls)
    assert len(client.calls) == 2
    assert not state["active_entities"].get("replans")
    _assert_no_effects(state, tmp_path)


def test_repaired_wrong_completed_source_operation_is_rejected_before_builder_runs(tmp_path):
    repair = {"steps": [_step("fresh_report", "reports.build_snapshot", {
        "title": "Observed sales", "sources": [{"source_id": "x", "source_step_id": "step_1",
            "operation_id": "stock.inventory_overview", "result": {"$from_step": "step_1", "path": "tool_result"}}],
        "sheets": [{"name": "Rows", "source_id": "x", "rows_path": "", "columns": [
            {"key": "count", "label": "Count", "source_path": "total_orders", "data_type": "integer"}]}]},
        ["step_1"], "Project an observed source", ["report_snapshot"])]}
    state, client = _run(tmp_path, repair, max_steps=24)
    assert state["status"] == "failed" and len(state["completed_steps"]) == 2
    replan = state["active_entities"]["replans"][0]
    assert replan["contract_repair"]["applied"] is False and replan["accepted_step_ids"] == []
    assert any("binding_source_operation_mismatch" in code
               for row in replan["validation_diagnostics"] for code in row["reason_codes"])
    assert state["active_entities"]["execution_budget"]["started_steps"] == 2
    assert len([row for row in client.calls if row["kind"] == "contract_repair"]) == 1
    _assert_no_effects(state, tmp_path)
