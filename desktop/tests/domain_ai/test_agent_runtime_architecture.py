"""Agent-owned choices over one neutral tool boundary and full contracts."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from AI.processors import model_loop, tools, task_runtime, cloud_runtime, operation_catalog
from AI.processors.session_state import AgentSessionState
from AI.processors.source_policy import EXISTING_ONLY
from AI.runtime import arguments, contracts
from AI.runtime.catalog import record_discovered_tools, select_tool_menu, tool_definitions
from AI.runtime.schema import validate_tool_arguments
from Feedback.processors.pipeline import Result
from Testing.processors.business_agent_fixtures import seed_business_fixture


class Model:
    def __init__(self, responses, inspect_menu=None):
        self.responses = iter(responses)
        self.prompts = []
        self.menus = []
        self.inspect_menu = inspect_menu
        self.resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}

    def invoke_tools(self, prompt, *, tools):
        self.prompts.append(prompt)
        self.menus.append([tool["name"] for tool in tools])
        if self.inspect_menu:
            self.inspect_menu(self)
        value = next(self.responses)
        return value if isinstance(value, str) else json.dumps(value)


def call(name, **arguments):
    return {"mode": "tool", "tool": name, "arguments": arguments}


def read_tool(name, handler=None, **options):
    return contracts.AgentTool(name=name, description="One native operation", parameters={
        "type": "object", "properties": {}, "additionalProperties": False},
        handler=handler or (lambda: Result.ok("Observed", data={"count": 1})), **options)


def test_shared_primitives_have_one_owner_and_legacy_keeps_import_compatibility():
    assert tools.AgentTool is contracts.AgentTool
    assert tools.OperationInputSource is contracts.OperationInputSource
    assert task_runtime._resolve_argument_value is arguments._resolve_argument_value
    assert task_runtime._source_bound_operation_argument_problems is arguments._source_bound_operation_argument_problems
    assert tools.AgentTool.__module__ == "AI.runtime.contracts"


def test_every_registered_input_contract_is_valid_json_schema():
    from jsonschema import Draft202012Validator
    for tool in tools.registered_tools().values():
        Draft202012Validator.check_schema(tool.parameters)


def test_same_loop_supports_a_guarded_json_provider_without_native_functions(tmp_path):
    database = str(tmp_path / "fixture.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    class JsonModel:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": False}}
        def __init__(self):
            self.responses = iter([
                {"tool": "orders.summary", "arguments_json": '{"period":"all"}', "answer": ""},
                {"tool": "", "arguments_json": "{}", "answer": "Kayıtlı 6 sipariş var."}])
        def __call__(self, prompt):
            return json.dumps(next(self.responses))
    result = model_loop.run_model_loop("Siparişlerime bak", client=JsonModel(), db_name=database)
    assert result.success and result.data["answer"] == "Kayıtlı 6 sipariş var."
    assert result.data["direct_tool_results"][0]["data"]["total_orders"] == 6


@pytest.mark.parametrize("value,reason", [
    ({"ids": []}, "arguments.ids:minItems"),
    ({"ids": [1, 2, 3]}, "arguments.ids:maxItems"),
    ({"ids": [1, 1]}, "arguments.ids:uniqueItems"),
    ({"ids": [True]}, "arguments.ids[0]:type"),
    ({"ids": [1], "code": "bad"}, "arguments.code:pattern"),
    ({"ids": [1], "option": "both"}, "arguments.option:oneOf"),
    ({"ids": [1], "amount": float("nan")}, "arguments.amount:nonfinite_number"),
])
def test_full_json_schema_is_enforced_without_exposing_values(value, reason):
    tool = SimpleNamespace(parameters={"type": "object", "required": ["ids"], "additionalProperties": False,
        "$defs": {"id": {"type": "integer"}}, "properties": {
            "ids": {"type": "array", "minItems": 1, "maxItems": 2, "uniqueItems": True,
                    "items": {"$ref": "#/$defs/id"}},
            "code": {"type": "string", "pattern": "^[A-Z]{3}$"},
            "option": {"oneOf": [{"const": "left"}, {"const": "right"}]},
            "amount": {"type": "number"}}})
    problems = validate_tool_arguments(tool, value)
    assert reason in problems
    assert "bad" not in json.dumps(problems) and "both" not in json.dumps(problems)
    assert not validate_tool_arguments(tool, {"ids": [1, 2], "code": "ABC", "option": "left", "amount": 2.5})


def test_tool_schema_reference_cannot_make_an_unrequested_network_source():
    tool = SimpleNamespace(parameters={"type": "object", "$ref": "https://schema.example/private"})
    assert validate_tool_arguments(tool, {}) == ["arguments:invalid_tool_schema"]


def test_malformed_source_shape_is_a_repairable_argument_error(tmp_path):
    result = model_loop.run_model_loop("Rapor hazırla", client=Model([
        call("reports.build_snapshot", title="Rapor", sources=42, sheets=[]),
        "Kaynak dizisi geçerli değil; önce kayıtlı kaynağı belirlemeliyim."]), db_name=str(tmp_path / "unused.db"))
    assert result.success and not result.data["approval_required"]
    failed = result.data["direct_tool_results"][0]
    assert not failed["success"] and "arguments.sources:type" in failed["data"]["argument_problems"]
    assert "error_type" not in failed["data"]


def test_model_repairs_array_validation_before_any_native_prepare(tmp_path, monkeypatch):
    database = str(tmp_path / "fixture.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    invocations = []
    original = tools.orders_prepare_fetch
    from functools import wraps
    @wraps(original)
    def observed(**kwargs):
        invocations.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(tools, "orders_prepare_fetch", observed)
    model = Model([call("orders.fetch.prepare", api_account_ids=[]),
                   call("orders.fetch.prepare", api_account_ids=[101]), "Tek mağaza için onay bekliyorum."])
    result = model_loop.run_model_loop("Pilot Ana için sipariş çekmeyi hazırla", client=model, db_name=database)
    assert result.success and result.data["approval_required"], result.data
    assert len(invocations) == 1 and invocations[0]["api_account_ids"] == [101]
    assert "minItems" in model.prompts[1]
    assert result.data["state"]["completed_steps"][0]["status"] == "failed"
    assert result.data["action_proposal"]["api_call_performed"] is False


def test_past_read_contract_can_bind_a_new_report_without_fresh_source_authority(tmp_path, monkeypatch):
    database = str(tmp_path / "fixture.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    first = model_loop.run_model_loop("Kayıtlı siparişleri oku", client=Model([
        call("orders.snapshot"), "Kayıtlı 6 sipariş var."]), db_name=database)
    def forbidden(*a, **k):
        pytest.fail("Existing-source report must not re-read the database")
    monkeypatch.setattr("Orders.views.actions.action_load_order_snapshot", forbidden)
    client = Model([call("reports.build_snapshot", title="Kayıtlı siparişler", sources=[{
        "source_id": "orders", "source_step_id": "call_1", "operation_id": "orders.snapshot",
        "result": {"$from_step": "call_1", "path": "tool_result"}}], sheets=[{
            "name": "Siparişler", "source_id": "orders", "rows_path": "orders", "columns": [
                {"key": "number", "label": "Sipariş", "source_path": "order_number", "data_type": "string"}]}]),
        call("reports.xlsx.prepare", report_snapshot={"$from_step": "call_2", "path": "tool_result.report_snapshot"}),
        "Aynı kayıtlardan raporu hazırladım."])
    result = model_loop.run_model_loop("Yeni kaynak okumadan bu kayıtlarla Excel hazırla", client=client,
        db_name=database, session_state=first.data["state"], runtime_context={"source_policy": EXISTING_ONLY})
    assert result.success and result.data["approval_required"], result.data
    snapshot = result.data["action_proposal"]["arguments"]["payload"]["report_snapshot"]
    assert len(snapshot["sheets"][0]["rows"]) == 6
    assert [c["tool"] for c in result.data["direct_tool_calls"]] == ["reports.build_snapshot", "reports.xlsx.prepare"]
    assert "orders.snapshot" not in client.menus[0]


def test_source_bound_tool_definitions_keep_outputs_and_approval_together():
    tool = tools.registered_tools()["reports.xlsx.prepare"]
    descriptor = tool_definitions({tool.name: tool})[0]
    assert "Output fields:" in descriptor["description"]
    assert "Prepare only" in descriptor["description"]
    assert "completed-source bindings" in descriptor["description"]
    descriptor["parameters"]["properties"].clear()
    assert tool.parameters["properties"]


def test_stock_aggregation_is_owned_by_domain_and_shared_by_manual_and_ai(tmp_path, monkeypatch):
    from Stock.views import actions
    from Stock.processors import inventory_summary as domain
    database = str(tmp_path / "fixture.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    seen = []
    for function_name, action_name, ai_function in (
        ("read_inventory_overview", "action_inventory_overview", tools.stock_inventory_overview),
        ("read_low_stock_summary", "action_low_stock_summary", tools.low_stock_summary),
    ):
        original = getattr(domain, function_name)
        def observed(_original=original, **kwargs):
            seen.append(_original.__name__)
            return _original(**kwargs)
        monkeypatch.setattr(domain, function_name, observed)
        manual = getattr(actions, action_name)(db_name=database)
        ai = ai_function(db_name=database)
        assert manual.success and ai.success
        assert manual.data == {key:value for key,value in ai.data.items() if key != "tool"}
        assert seen[-2:] == [function_name, function_name]
    overview = domain.read_inventory_overview(db_name=database)
    assert overview.data["stock_value_by_currency"] == [{"currency": "TRY", "amount": 400}, {"currency": "USD", "amount": 30}]
    from Stock.processors.pipeline import database_scope
    with database_scope(database):
        scoped = actions.action_inventory_overview()
    assert scoped.data == overview.data


@pytest.mark.parametrize("family", ["openai", "anthropic", "gemini"])
def test_provider_does_not_silently_drop_tools_or_contract_text(family):
    description = "Read one operation. " + "x" * 1600 + " END-OF-CONTRACT"
    definitions, _ = cloud_runtime._provider_tool_definitions([
        {"name": "example.read", "description": description, "parameters": {"type": "object"}}], family=family)
    descriptor = definitions[0].get("function") or definitions[0]
    assert descriptor["description"] == description
    with pytest.raises(ValueError, match="transport window"):
        cloud_runtime._provider_tool_definitions([{"name": f"example.{i}"} for i in range(129)], family=family)


def test_model_can_discover_and_run_the_last_tool_beyond_a_128_tool_menu(tmp_path, monkeypatch):
    registry = {"operations.discover": tools.registered_tools()["operations.discover"]}
    registry.update({f"example.read_{i}": read_tool(f"example.read_{i}") for i in range(140)})
    monkeypatch.setattr(tools, "available_tools", lambda: registry)
    monkeypatch.setattr(operation_catalog, "available_tools", lambda: registry)
    model = Model([call("operations.discover", query="example.read_139", limit=1),
                   call("example.read_139"), "Son aracı buldum ve sonucunu okudum."])
    result = model_loop.run_model_loop("Son araca eriş", client=model, db_name=str(tmp_path / "unused.db"))
    assert result.success, result.data
    assert model.menus[0] == ["operations.discover"]
    assert "example.read_139" in model.menus[1] and max(map(len, model.menus)) <= 128
    assert result.data["direct_tool_results"][-1]["success"]


def test_discovery_does_not_restore_revoked_source_or_child_authority():
    state = AgentSessionState(goal="Inspect permitted contracts")
    state.active_entities["model_loop"] = {"loaded_tool_names": ["private.read"]}
    registry = {"example.allowed": read_tool("example.allowed")}
    record_discovered_tools(state, {"operations": [{"exposed_tool_name": "private.read"}]}, registry)
    assert "private.read" not in select_tool_menu(registry, state)


def test_pause_is_observed_between_tools_in_the_same_model_batch(tmp_path, monkeypatch):
    from AI.processors.task_control import AgentTaskControl
    control = AgentTaskControl()
    invoked = []
    def first():
        invoked.append("first")
        control.request_pause()
        return Result.ok("Observed", data={"count": 1})
    registry = {"example.first": read_tool("example.first", first),
                "example.second": read_tool("example.second", lambda: pytest.fail("Paused batch continued"))}
    monkeypatch.setattr(tools, "available_tools", lambda: registry)
    result = model_loop.run_model_loop("İki kaynağı incele", client=Model([
        {"mode": "tools", "calls": [call("example.first"), call("example.second")]}]),
        db_name=str(tmp_path / "unused.db"), task_control=control)
    assert result.success and result.data["state"]["status"] == "paused"
    assert invoked == ["first"] and len(result.data["direct_tool_calls"]) == 1
    assert result.data["state"]["active_entities"]["model_loop"]["feedback"][-1]["reason"] == "human_pause"


def test_extra_batch_calls_are_reported_to_the_model_instead_of_disappearing(tmp_path, monkeypatch):
    registry = {f"example.read_{i}": read_tool(f"example.read_{i}") for i in range(9)}
    monkeypatch.setattr(tools, "available_tools", lambda: registry)
    calls = [{"tool": name, "arguments": {}} for name in registry]
    model = Model([{"mode": "tools", "calls": calls}, call("example.read_8"), "Dokuzunu da okudum."])
    result = model_loop.run_model_loop("Dokuz kaynağı incele", client=model, db_name=str(tmp_path / "unused.db"))
    assert result.success and len(result.data["direct_tool_calls"]) == 9
    assert '"not_executed_tool_calls"' in model.prompts[1] and "example.read_8" in model.prompts[1]
    payload = {"choices": [{"message": {"tool_calls": [{"type": "function", "function": {
        "name": name, "arguments": "{}"}} for name in registry]}}]}
    normalized = cloud_runtime._extract_openai_tool_decision(payload, wire_to_source={name: name for name in registry})
    assert len(json.loads(normalized)["calls"]) == 9
