"""Real child plans/read sources; only structured model responses are fixtures."""
from copy import deepcopy
import json

from openpyxl import load_workbook
import pytest

from AI.processors import child_task_runtime as children, tools, file_workspace, observation_artifacts
from AI.processors.business_acceptance_fixtures import seed_business_fixture
from AI.processors.session_state import ActiveScope, AgentSessionState
from AI.processors.task_control import AgentTaskControl
from AI.processors.task_runtime import run_agent_task, resume_read_task
from AI.processors.task_store import load_agent_task_state
from AI.processors.turn_service import run_typed_control_turn


@pytest.fixture
def database(tmp_path):
    database = tmp_path / "business.sqlite3"
    seed_business_fixture(str(database), isolation_root=tmp_path)
    return database


class Model:
    def __init__(self, parent_plan, child_plan):
        self.parent_plan, self.child_plan = parent_plan, child_plan
        self.prompts, self.reservations = [], []

    def reserve_task_budget(self, **options):
        self.reservations.append(options)

    def __call__(self, prompt):
        child = children.current_child_policy() is not None
        self.prompts.append((child, prompt))
        if prompt.startswith("OrderScout semantic action verifier"):
            return json.dumps({"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
                               "unwanted_effect": False, "reason": "User requested the exact current report"})
        if prompt.startswith("GoalPlan observation"):
            return json.dumps({"decision": "complete" if child else "continue", "reason": "The declared source read is complete"})
        return json.dumps(self.child_plan if child else self.parent_plan)


def _delegate(*, steps=1, replans=0, objective="Independently read the current stock and separate currencies"):
    return {"id": "delegated", "operation_id": "agent.delegate", "depends_on": [],
            "objective": "Delegate an independent current stock read", "expected_evidence": ["child_status", "artifact_refs"],
            "arguments": {"objective": objective, "max_steps": steps, "max_replans": replans}}


def _read(operation="stock.inventory_overview", arguments=None):
    return {"steps": [{"id": "child_source", "operation_id": operation, "depends_on": [],
                       "objective": "Read real authoritative source", "arguments": arguments or {},
                       "expected_evidence": (["stock_value_by_currency"] if operation == "stock.inventory_overview"
                                             else ["rows", "source_hash"] if operation == "files.read" else ["total_orders"])}]}


def _run(database, model, *, steps=8, previous=None, **options):
    return run_agent_task("Delegate independent research and use actual sources to prepare my report", domain="general",
        planner_client=model, db_name=str(database), max_steps=steps, session_state=previous,
        turn_interpretation={"mode": "act", "domain": "general", "intent_kind": "action", "valid": True,
                             "requested_fields": ["artifact"], "requires_clarification": False}, **options)


def test_independent_child_real_read_parent_artifact_binding_report_approval_and_readback(database, tmp_path):
    output = tmp_path / "from-child.xlsx"
    parent_plan = {"steps": [_delegate(),
        {"id": "import_child", "operation_id": "artifacts.read", "depends_on": ["delegated"],
         "arguments": {"artifact_id": {"$from_step": "delegated", "path": "tool_result.artifact_refs[0].artifact_id"}},
         "expected_evidence": ["result", "origin"]},
        {"id": "report", "operation_id": "reports.build_snapshot", "depends_on": ["import_child"],
         "arguments": {"title": "Child source report", "sources": [{"source_id": "stock", "source_step_id": "import_child",
            "operation_id": "artifacts.read", "result": {"$from_step": "import_child", "path": "tool_result"}}],
            "sheets": [{"name": "Stok", "source_id": "stock", "rows_path": "result.stock_value_by_currency", "columns": [
                {"key": "currency", "label": "Döviz", "source_path": "currency", "data_type": "string"},
                {"key": "amount", "label": "Değer", "source_path": "amount", "data_type": "number"}]}]},
         "expected_evidence": ["report_snapshot"]},
        {"id": "prepare", "operation_id": "reports.xlsx.prepare", "depends_on": ["report"],
         "arguments": {"report_snapshot": {"$from_step": "report", "path": "tool_result.report_snapshot"}, "output_path": str(output)},
         "expected_evidence": ["action"]}]}
    model = Model(parent_plan, _read())
    started = _run(database, model, persist=True, task_store_root=str(tmp_path / "tasks"))
    assert started.success, started.message
    state = started.data["state"]
    assert state["status"] == "pending_approval", [(row["step_id"], row["status"], row["result_message"]) for row in state["completed_steps"]]
    assert [row["tool_names"] for row in state["completed_steps"]] == [["agent.delegate"], ["artifacts.read"], ["reports.build_snapshot"], ["reports.xlsx.prepare"]]
    receipt = state["completed_steps"][0]["result_data"]["tool_result"]
    assert receipt["child_status"] == "complete" and receipt["child_started_steps"] == 1
    assert receipt["child_task_id"] != state["session_id"]
    assert receipt["business_observations_in_receipt"] is False and receipt["effect_authority"] is False
    assert receipt["artifact_refs"][0]["origin"]["task_id"] == receipt["child_task_id"]
    actual = state["completed_steps"][1]["result_data"]["tool_result"]
    assert actual["historical_observation"] is True and actual["fresh_read"] is False
    assert actual["artifact"]["origin"]["task_id"] == receipt["child_task_id"]
    assert {row["currency"]: row["amount"] for row in actual["result"]["stock_value_by_currency"]} == {"TRY": 400, "USD": 30}
    child = json.loads((tmp_path / "tasks" / (receipt["child_task_id"] + ".json")).read_text(encoding="utf-8"))
    assert child["active_entities"]["child_delegation_policy"]["effects_allowed"] is False
    assert child["completed_steps"][0]["tool_names"] == ["stock.inventory_overview"]
    assert state["active_entities"]["execution_budget"]["started_steps"] == 5
    assert model.reservations == [{"max_steps": 8}]
    assert any(flag for flag, _ in model.prompts) and not output.exists()
    approved = run_typed_control_turn("Onaylıyorum.", mode="approve", session_state=state, client=None,
                                      db_name=str(database), allow_approval_execute=True)
    assert approved.success, approved.message
    assert approved.data["execute"]["verify"]["verified_by"] == "xlsx_exact_snapshot_readback"
    workbook = load_workbook(output, read_only=True, data_only=False)
    try:
        assert list(workbook["Stok"].values) == [("Döviz", "Değer"), ("TRY", 400), ("USD", 30)]
    finally:
        workbook.close()


@pytest.mark.parametrize("operation,arguments", [
    ("reports.xlsx.prepare", {"report_snapshot": {}, "output_path": "forbidden.xlsx"}),
    ("agent.delegate", {"objective": "Another child"}),
    ("operations.manual_action.route", {"query": "write anything"}),
])
def test_child_model_cannot_prepare_execute_or_recursively_delegate(database, operation, arguments):
    model = Model({"steps": [_delegate(steps=2, replans=1)]}, _read(operation, arguments))
    started = _run(database, model)
    assert started.success
    state = started.data["state"]
    assert state["status"] != "complete" and not state["pending_actions"]
    assert state["active_entities"]["execution_budget"]["started_steps"] == 3
    assert state["active_entities"]["execution_budget"]["reserved_child_replans"] == 1
    child_prompts = [text for flag, text in model.prompts if flag]
    assert child_prompts
    # No forbidden operation contract is available to the child's planner.
    assert all('"operation_id":"reports.xlsx.prepare"' not in text for text in child_prompts)


def test_child_missing_account_argument_is_runtime_bound_and_cannot_widen(database):
    previous = AgentSessionState(goal="Only primary account", active_domain="general")
    previous.set_active_scope(ActiveScope.create(domain="orders", account_ids=[101], environments=["stage"]))
    model = Model({"steps": [_delegate(objective="Read current orders summary for the inherited account")]}, _read("orders.summary", {"period": "all"}))
    started = _run(database, model, previous=previous)
    state = started.data["state"]
    reservation = next(iter(state["active_entities"]["child_task_reservations"].values()))
    assert reservation["receipt"]["child_status"] == "complete", reservation
    child_call = next(text for flag, text in model.prompts if flag and text.startswith("GoalPlan observation"))
    assert '"requested_api_account_ids":[101]' in child_call or '"requested_api_account_ids": [101]' in child_call
    bad = Model({"steps": [_delegate(objective="Read current orders summary for the inherited account")]}, _read("orders.summary", {"period": "all", "api_account_ids": [102]}))
    blocked = _run(database, bad, previous=previous).data["state"]
    assert blocked["status"] != "complete"
    assert all(row.get("child_status") != "complete" for row in [value.get("receipt", {}) for value in blocked["active_entities"]["child_task_reservations"].values()])


def test_delegation_cannot_exceed_parent_budget_or_reset_provider_deadline(database):
    model = Model({"steps": [_delegate(steps=3)]}, _read())
    state = _run(database, model, steps=2).data["state"]
    assert state["status"] != "complete"
    assert not [prompt for flag, prompt in model.prompts if flag]
    assert state["active_entities"]["execution_budget"]["started_steps"] == 1
    assert model.reservations == [{"max_steps": 2}]


def test_child_cooperates_with_pause_and_never_claims_parent_completion(database):
    control = AgentTaskControl()
    model = Model({"steps": [_delegate()]}, _read())
    original = model.__class__.__call__
    class PausingModel(Model):
        def __call__(self, prompt):
            response = original(self, prompt)
            if children.current_child_policy() is not None:
                control.request_pause()
            return response
    paused = _run(database, PausingModel(model.parent_plan, model.child_plan), task_control=control).data["state"]
    assert paused["status"] == "paused"
    assert paused["active_entities"]["goal_progress"]["complete"] is False
    reservation = next(iter(paused["active_entities"]["child_task_reservations"].values()))
    assert reservation["status"] == "paused"


def test_private_runtime_authority_cannot_be_fabricated_as_model_arguments():
    result = children.delegate_read_task(objective="Research anything", runtime_context={"parent_state": {"status": "running"}})
    assert not result.success
    parent_registry = tools.available_tools()
    policy = children._scope_policy(AgentSessionState(goal="Current task"))
    with children.child_read_context(policy):
        child_registry = tools.available_tools()
        assert "agent.delegate" not in child_registry and "reports.xlsx.prepare" not in child_registry
        discovery = child_registry["operations.discover"].handler(limit=64)
        assert discovery.success
        assert all(row["operation_id"] in child_registry for row in discovery.data["operations"])
        assert all(row["operation_metadata"]["effect_class"] == "read" and row["operation_metadata"]["risk_level"] == "R0"
                   and row["operation_metadata"]["approval_policy"] == "none" for row in discovery.data["operations"])
        manual = child_registry["operations.discover"].handler(limit=64, include_manual=True)
        assert manual.success
        assert all(row["operation_id"] in child_registry for row in manual.data["operations"])
        bound, problems = children.bind_child_read_arguments(child_registry["operations.discover"], {})
        assert not problems and bound["include_manual"] is False
    assert "agent.delegate" in parent_registry and "reports.xlsx.prepare" in parent_registry
    assert children.current_child_policy() is None


def _paused_orders_child(database, tmp_path):
    control = AgentTaskControl()
    previous = AgentSessionState(goal="Only primary account", active_domain="general")
    previous.set_active_scope(ActiveScope.create(domain="orders", account_ids=[101], environments=["stage"]))
    child_plan = _read("orders.summary", {"period": "all"})
    child_plan["steps"].append({"id": "second_source", "operation_id": "orders.count", "depends_on": ["child_source"],
                                "arguments": {"period": "all"}, "expected_evidence": ["count"]})
    class PauseAfterObservation(Model):
        def __call__(self, prompt):
            response = super().__call__(prompt)
            if children.current_child_policy() is not None and prompt.startswith("GoalPlan observation"):
                control.request_pause()
                return json.dumps({"decision": "continue", "reason": "The second source is still required"})
            return response
    model = PauseAfterObservation({"steps": [_delegate(steps=2, replans=1, objective="Read current account orders summary and order count")]}, child_plan)
    parent = _run(database, model, previous=previous, task_control=control, persist=True,
                  task_store_root=str(tmp_path / "tasks")).data["state"]
    reservation = next(iter(parent["active_entities"]["child_task_reservations"].values()))
    child = load_agent_task_state(reservation["child_task_id"], root=tmp_path / "tasks")
    assert parent["status"] == child.status == "paused"
    assert len(child.completed_steps) == len(child.remaining_steps) == 1
    assert parent["active_entities"]["task_checkpoint"]["inflight_step"]["operation_candidates"] == ["agent.delegate"]
    assert parent["active_entities"]["execution_budget"]["started_steps"] == 3
    assert child.active_entities["child_delegation_policy"]["account_ids"] == {"orders": ["101"]}
    return parent, child


def test_paused_parent_resumes_same_durable_child_without_new_reservation(database, tmp_path):
    parent, child = _paused_orders_child(database, tmp_path)
    model = Model({"steps": []}, {"steps": []})
    resumed = resume_read_task(parent, planner_client=model, db_name=str(database), persist=True,
                               task_store_root=str(tmp_path / "tasks"), task_control=AgentTaskControl())
    assert resumed.success, resumed.message
    final = resumed.data["state"]
    receipt = final["completed_steps"][0]["result_data"]["tool_result"]
    assert receipt["child_task_id"] == child.session_id and receipt["child_status"] == "complete"
    assert final["active_entities"]["execution_budget"]["started_steps"] == 3
    assert final["active_entities"]["execution_budget"]["reserved_child_replans"] == 1
    restored = load_agent_task_state(child.session_id, root=tmp_path / "tasks")
    assert len(restored.completed_steps) == 2 and restored.active_entities["execution_budget"]["started_steps"] == 2
    assert restored.completed_steps[1].result_data["tool_result"]["requested_api_account_ids"] == [101]
    assert final["status"] != "complete" and final["active_entities"]["goal_progress"]["complete"] is False
    assert len(model.reservations) == 1  # Only normal parent continuation reserves provider time.
    assert children.current_child_policy() is None


def test_parent_durable_recovery_consumes_already_completed_child_without_repeating_sources(database, tmp_path):
    parent, child = _paused_orders_child(database, tmp_path)
    finished = resume_read_task(child, planner_client=Model({"steps": []}, {"steps": []}), db_name=str(database),
                               persist=True, task_store_root=str(tmp_path / "tasks"), task_control=AgentTaskControl())
    assert finished.success and finished.data["state"]["status"] == "complete"
    model = Model({"steps": []}, {"steps": []})
    resumed = resume_read_task(parent, planner_client=model, db_name=str(database), persist=True,
                               task_store_root=str(tmp_path / "tasks"), task_control=AgentTaskControl())
    final = resumed.data["state"]
    actual = final["completed_steps"][0]["result_data"]["tool_result"]
    assert actual["child_task_id"] == child.session_id and actual["child_status"] == "complete"
    assert final["active_entities"]["execution_budget"]["started_steps"] == 3
    assert not [prompt for flag, prompt in model.prompts if flag]
    restored = load_agent_task_state(child.session_id, root=tmp_path / "tasks")
    assert len(restored.completed_steps) == 2 and restored.active_entities["execution_budget"]["started_steps"] == 2


def test_parent_scope_change_cannot_resume_or_reuse_previous_child_reservation(database, tmp_path):
    parent, child = _paused_orders_child(database, tmp_path)
    state = AgentSessionState.from_dict(parent)
    state.set_active_scope(ActiveScope.create(domain="orders", account_ids=[102], environments=["stage"]))
    model = Model({"steps": []}, {"steps": []})
    resumed = resume_read_task(state, planner_client=model, db_name=str(database), persist=True,
                               task_store_root=str(tmp_path / "tasks"), task_control=AgentTaskControl())
    final = resumed.data["state"]
    assert final["status"] != "complete" and final["completed_steps"][0]["status"] == "failed"
    assert final["completed_steps"][0]["result_data"]["tool_result"]["child_scope_changed"] is True
    assert final["active_entities"]["execution_budget"]["started_steps"] == 3
    assert not [prompt for flag, prompt in model.prompts if flag]
    assert load_agent_task_state(child.session_id, root=tmp_path / "tasks").status == "paused"


@pytest.mark.parametrize("operation,arguments", [
    ("reports.xlsx.prepare", {"report_snapshot": {}, "output_path": "forbidden.xlsx"}),
    ("agent.delegate", {"objective": "Another child"}),
    ("orders.count", {"period": "all", "api_account_ids": [102]}),
])
def test_durable_child_resume_never_restores_effect_recursion_or_wider_account(database, tmp_path, operation, arguments):
    _, child = _paused_orders_child(database, tmp_path)
    child.remaining_steps[0].operation_candidates = [operation]
    child.remaining_steps[0].operation_domain = tools.available_tools()[operation].domain
    child.remaining_steps[0].arguments = arguments
    model = Model({"steps": []}, {"steps": []})
    resumed = resume_read_task(child, planner_client=model, db_name=str(database), persist=True,
                               task_store_root=str(tmp_path / "tasks"), task_control=AgentTaskControl())
    final = resumed.data["state"]
    assert final["status"] != "complete" and not final["pending_actions"]
    assert not model.reservations
    assert not [row for row in final["completed_steps"] if row["status"] == "completed" and row["step_id"] == "second_source"]
    assert all(flag for flag, _ in model.prompts)  # Scope restored before any model call.
    assert children.current_child_policy() is None


def test_actual_provider_absolute_deadline_and_durable_reservation_precede_child_model(database, tmp_path, monkeypatch):
    from AI.processors import cloud_runtime
    provider = cloud_runtime.build_provider_chat_client({"provider_code": "custom", "endpoint_url": "https://provider.invalid/v1",
        "default_model": "test-model", "is_enabled": True, "allow_model_fallback": False})
    monkeypatch.setattr(cloud_runtime.time, "monotonic", lambda: 100)
    cloud_runtime.begin_provider_chat_turn(provider)
    parent_ids, deadlines, checkpoints = [], [], []
    class ProviderModel(Model):
        def reserve_task_budget(self, **options):
            super().reserve_task_budget(**options)
            provider.reserve_task_budget(**options)
        def __call__(self, prompt):
            deadlines.append(provider.turn_deadline_monotonic)
            if children.current_child_policy() is not None:
                parent = load_agent_task_state(parent_ids[0], root=tmp_path / "tasks")
                reservation = next(iter(parent.active_entities["child_task_reservations"].values()))
                checkpoints.append((parent.active_entities["execution_budget"]["started_steps"], reservation["child_task_id"]))
                durable_child = load_agent_task_state(reservation["child_task_id"], root=tmp_path / "tasks")
                assert durable_child.active_entities["child_delegation_policy"]["effects_allowed"] is False
            return super().__call__(prompt)
    model = ProviderModel({"steps": [_delegate(steps=1, replans=1)]}, _read())
    result = _run(database, model, persist=True, task_store_root=str(tmp_path / "tasks"),
                  task_created_callback=lambda state: parent_ids.append(state.session_id))
    state = result.data["state"]
    assert checkpoints and all(charged == 2 and task_id for charged, task_id in checkpoints)
    assert provider.turn_started_monotonic == 100 and set(deadlines) == {1000}
    assert model.reservations == [{"max_steps": 8}]
    assert state["active_entities"]["execution_budget"]["reserved_child_replans"] == 1
    assert state["status"] != "complete"  # A delegation receipt cannot satisfy the parent report.


def test_cross_owner_scopes_cannot_union_accounts_or_discover_unbound_owner_reads(database):
    parent = AgentSessionState(goal="Two independent scoped owners")
    parent.set_active_scope(ActiveScope.create(domain="orders", account_ids=[101], environments=["stage"]))
    parent.set_active_scope(ActiveScope.create(domain="returns", account_ids=[102], environments=["prod"]))
    policy = children._scope_policy(parent)
    with children.child_read_context(policy):
        registry = tools.available_tools()
        assert children._scope_values(policy, "account_ids", "orders") == ["101"]
        assert children._scope_values(policy, "account_ids", "finance") == []
        assert not [name for name, tool in registry.items() if tool.domain == "finance"]
        bound, problems = children.bind_child_read_arguments(registry["orders.summary"], {"period": "all", "api_account_ids": [102]})
        assert "child_scope_widening:api_account_ids" in problems
        discovered = registry["operations.discover"].handler(include_manual=True, limit=64)
        assert all(row["operation_id"] in registry for row in discovered.data["operations"])


def test_inherited_artifact_grant_cannot_widen_child_current_account_scope(database, tmp_path):
    previous = AgentSessionState(goal="Only secondary account", active_domain="general")
    previous.set_active_scope(ActiveScope.create(domain="orders", account_ids=[102], environments=["stage"]))
    observed = _run(database, Model(_read("orders.summary", {"period": "all"}), {"steps": []}), previous=previous)
    parent = AgentSessionState.from_dict(observed.data["state"])
    actual = parent.completed_steps[0].result_data["tool_result"]
    assert actual["requested_api_account_ids"] == [102]
    artifact_id = observation_artifacts.observation_artifact_refs(parent)[0]["artifact_id"]
    parent.set_active_scope(ActiveScope.create(domain="orders", account_ids=[101], environments=["stage"]))
    model = Model({"steps": [_delegate(objective="Read the granted historical order observation")]},
                  _read("artifacts.read", {"artifact_id": artifact_id}))
    result = _run(database, model, previous=parent, persist=True, task_store_root=str(tmp_path / "tasks"))
    receipt = result.data["state"]["completed_steps"][0]["result_data"]["tool_result"]
    child = load_agent_task_state(receipt["child_task_id"], root=tmp_path / "tasks")
    assert receipt["child_status"] != "complete" and not receipt["artifact_refs"]
    assert child.completed_steps[0].status == "failed"
    assert "gözlenen kapsam" in child.completed_steps[0].result_message


def test_child_reads_only_parent_selected_attachment_and_returns_actual_source_hash(database, tmp_path, monkeypatch):
    monkeypatch.setattr(file_workspace, "ATTACHMENTS_ROOT", tmp_path / "imports")
    monkeypatch.setattr(observation_artifacts, "OBSERVATION_ARTIFACTS_ROOT", tmp_path / "observations")
    parent = AgentSessionState(goal="Read selected file", active_domain="general")
    selected = tmp_path / "chosen.json"
    selected.write_text(json.dumps([{"sku": "001", "quantity": 4}]), encoding="utf-8")
    metadata = file_workspace.register_attachment(selected, parent.session_id)
    parent.active_entities["file_workspace"] = {"session_id": parent.session_id, "attachments": [metadata]}
    model = Model({"steps": [_delegate(objective="Independently read the selected JSON attachment")]},
                  _read("files.read", {"attachment_id": metadata["attachment_id"]}))
    state = _run(database, model, previous=parent, persist=True, task_store_root=str(tmp_path / "tasks")).data["state"]
    receipt = state["completed_steps"][0]["result_data"]["tool_result"]
    child = load_agent_task_state(receipt["child_task_id"], root=tmp_path / "tasks")
    actual = child.completed_steps[0].result_data["tool_result"]
    assert receipt["child_status"] == "complete" and actual["source_hash"] == metadata["sha256"]
    assert actual["rows"] == [{"sku": "001", "quantity": 4}]
    assert child.active_entities["file_workspace"]["session_id"] == parent.session_id
    invalid = Model({"steps": [_delegate(objective="Read selected JSON attachment")]},
                    _read("files.read", {"attachment_id": "att_" + "f" * 32}))
    bad = _run(database, invalid, previous=parent).data["state"]
    assert bad["completed_steps"][0]["status"] == "failed"
    assert not bad["completed_steps"][0]["result_data"]["tool_result"]["artifact_refs"]
