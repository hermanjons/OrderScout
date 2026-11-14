"""Repairs for the observed discovery/count-arithmetic detours."""
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import json

import pytest
from sqlmodel import Session, select

from AI.processors import model_loop, tools
from AI.processors.analysis_operations import calculate_observations
from AI.processors.operation_catalog import discover_operation_catalog
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from Core.utils.model_utils import get_engine
from Orders.models.trendyol.models import OrderData
from Testing.processors.order_snapshot_fixture import seed_order_snapshot_fixture


def expression(path="status_counts.Delivered"):
    return {"calculation_id": "delivered_share", "operator": "percentage", "precision": 2,
            "operands": [{"source_id": "counts", "path": path},
                         {"source_id": "counts", "path": "total_orders"}]}


@pytest.fixture
def population(tmp_path):
    db = str(tmp_path / "synthetic.sqlite3")
    seed_order_snapshot_fixture(db, isolation_root=tmp_path)
    with Session(get_engine(db)) as session:
        rows = session.exec(select(OrderData)).all()
        oracle = dict(Counter(row.shipmentPackageStatus or row.status for row in rows))
    return db, oracle


@pytest.mark.parametrize("operation", ["orders.status_counts", "orders.summary", "orders.query", "orders.snapshot"])
def test_real_status_map_numeric_paths_are_usable_without_fetching_full_rows(population, operation):
    db, oracle = population
    registry = tools.available_tools()
    args = {"period": "all"}
    if operation == "orders.query":
        args["mode"] = "count"
    read = registry[operation].handler(db_name=db, **args)
    assert read.success and read.data["status_counts"] == oracle
    source = {"source_id": "counts", "source_step_id": "call_1", "operation_id": operation, "result": read.data}
    calculation = expression()
    if operation in {"orders.query", "orders.snapshot"}:
        calculation["operands"][1]["path"] = "total_count"
    result = calculate_observations(sources=[source], calculations=[calculation])
    assert result.success, result.data
    computed = result.data["verified_calculations"][0]
    expected = (Decimal(oracle["Delivered"]) / Decimal(sum(oracle.values())) * 100).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    assert computed["result"] == str(expected) and computed["unit"] == "%"
    assert computed["operand_receipts"][0]["unit"] == "order"
    assert computed["operand_receipts"][0]["path"] == "status_counts.Delivered"


def test_payload_and_arbitrary_nested_numeric_map_cannot_invent_declared_units():
    source = {"source_id": "counts", "source_step_id": "read", "operation_id": "orders.status_counts", "result": {
        "total_orders": 10, "nested": {"status_counts": {"Delivered": 5}},
        "unit": "order", "x-measure-unit": "order"}}
    result = calculate_observations(sources=[source], calculations=[expression("nested.status_counts.Delivered")])
    assert not result.success and result.data["reason"] == "analysis_measure_unit_unknown:nested.status_counts.Delivered"


def test_schema_unit_lookup_is_generic_and_comes_from_registered_output(monkeypatch):
    from AI.runtime.contracts import AgentTool
    custom = AgentTool(name="parcels.overview", domain="parcels", description="Parcel measures", handler=lambda: None,
        parameters={}, result_schema={"type": "object", "properties": {"buckets": {"type": "object",
            "additionalProperties": {"type": "number", "x-measure-unit": "parcel"}}}})
    monkeypatch.setattr(tools, "registered_tools", lambda: {custom.name: custom})
    result = calculate_observations(sources=[{"source_id": "counts", "source_step_id": "read", "operation_id": custom.name,
        "result": {"buckets": {"a": 2, "b": 3}}}], calculations=[{
            "calculation_id": "sum", "operator": "add", "operands": [
                {"source_id": "counts", "path": "buckets.a"}, {"source_id": "counts", "path": "/buckets/b"}]}])
    assert result.success and result.data["verified_calculations"][0]["unit"] == "parcel"
    assert result.data["verified_calculations"][0]["result_value"] == 5


@pytest.mark.parametrize("historical_depth", [0, 1, 2])
def test_dotted_pointer_alias_keeps_declared_unit_through_historical_wrappers(historical_depth):
    from AI.processors.observation_projection import source_projection_hash
    payload = {"total_orders": 10, "status_counts": {"Delivered": 4}, "api_account_ids": [7]}
    operation = "orders.status_counts"
    for depth in range(historical_depth):
        observed_at, scope = "2026-10-20T10:00:00+03:00", {"api_account_ids": [7]}
        payload = {"tool": "artifacts.read", "verified": True, "historical_observation": True,
            "fresh_read": False, "freshness": "historical_snapshot", "observed_at": observed_at, "scope": scope,
            "artifact": {"origin": {"task_id": f"prior_{depth}", "step_id": "read", "operation_id": operation},
                         "result_hash": source_projection_hash(payload), "observed_at": observed_at, "scope": scope},
            "result": payload}
        operation = "artifacts.read"
    prefix = "/" + "result." * historical_depth
    calculation = expression(prefix + "status_counts.Delivered")
    calculation["operands"][1]["path"] = prefix + "total_orders"

    result = calculate_observations(sources=[{"source_id": "counts", "source_step_id": "read",
        "operation_id": operation, "result": payload}], calculations=[calculation])

    assert result.success, result.data
    computed = result.data["verified_calculations"][0]
    assert computed["result_value"] == 40 and computed["unit"] == "%"
    assert computed["operand_receipts"][0]["path"] == prefix + "status_counts.Delivered"
    assert computed["operand_receipts"][0]["unit"] == "order"


@pytest.mark.parametrize("prefix,separator", [
    ("tool_result.", "."), ("/tool_result/", "/"), ("/tool_result.", "."),
    ("/tool_result/", "."),
])
@pytest.mark.parametrize("operator,expected,unit", [("add", 14, "order"), ("percentage", 40, "%")])
def test_optional_tool_result_prefix_resolves_relative_count_values_and_units(prefix, separator, operator, expected, unit):
    paths = [prefix + "status_counts" + separator + "Delivered", prefix + "total_orders"]
    result = calculate_observations(sources=[{"source_id": "counts", "source_step_id": "read",
        "operation_id": "orders.status_counts", "result": {"total_orders": 10, "status_counts": {"Delivered": 4}}}],
        calculations=[{"calculation_id": "measure", "operator": operator, "operands": [
            {"source_id": "counts", "path": path} for path in paths]}])

    assert result.success, result.data
    computed = result.data["verified_calculations"][0]
    assert computed["result_value"] == expected and computed["unit"] == unit
    assert [receipt["path"] for receipt in computed["operand_receipts"]] == paths
    assert [receipt["unit"] for receipt in computed["operand_receipts"]] == ["order", "order"]


@pytest.mark.parametrize("path", ["tool_result.count", "/tool_result/count", "/tool_result.count"])
@pytest.mark.parametrize("nested_present", [True, False])
def test_literal_tool_result_key_is_never_replaced_by_relative_alias(monkeypatch, path, nested_present):
    from AI.runtime.contracts import AgentTool
    custom = AgentTool(name="parcels.overview", description="Parcel measures", handler=lambda: None, parameters={},
        result_schema={"type": "object", "properties": {
            "count": {"type": "number", "x-measure-unit": "root_parcel"},
            "tool_result": {"type": "object", "properties": {
                "count": {"type": "number", "x-measure-unit": "nested_parcel"}}}}})
    monkeypatch.setattr(tools, "registered_tools", lambda: {custom.name: custom})
    result = calculate_observations(sources=[{"source_id": "counts", "source_step_id": "read",
        "operation_id": custom.name, "result": {"count": 20, "tool_result": {"count": 3} if nested_present else {}}}],
        calculations=[{"calculation_id": "sum", "operator": "add", "operands": [
            {"source_id": "counts", "path": path}, {"source_id": "counts", "path": path}]}])

    if nested_present:
        assert result.success, result.data
        computed = result.data["verified_calculations"][0]
        assert computed["result_value"] == 6 and computed["unit"] == "nested_parcel"
        assert computed["operand_receipts"][0]["path"] == path
    else:
        assert not result.success and result.data["reason"].startswith("observation_projection_path_missing:")
        assert result.data["failed_operand"]["path"] == path


def test_optional_prefix_preserves_exact_literal_dotted_pointer_key(monkeypatch):
    from AI.runtime.contracts import AgentTool
    custom = AgentTool(name="parcels.overview", description="Parcel measures", handler=lambda: None, parameters={},
        result_schema={"type": "object", "properties": {
            "count": {"type": "number", "x-measure-unit": "root_parcel"},
            "tool_result.count": {"type": "number", "x-measure-unit": "literal_parcel"}}})
    monkeypatch.setattr(tools, "registered_tools", lambda: {custom.name: custom})
    result = calculate_observations(sources=[{"source_id": "counts", "source_step_id": "read",
        "operation_id": custom.name, "result": {"count": 20, "tool_result.count": 2}}],
        calculations=[{"calculation_id": "sum", "operator": "add", "operands": [
            {"source_id": "counts", "path": "/tool_result.count"},
            {"source_id": "counts", "path": "/tool_result.count"}]}])

    assert result.success, result.data
    computed = result.data["verified_calculations"][0]
    assert computed["result_value"] == 4 and computed["unit"] == "literal_parcel"


@pytest.mark.parametrize("prefix,separator", [("tool_result.", "."), ("/tool_result/", "/"), ("/tool_result.", ".")])
def test_optional_prefix_keeps_historical_result_depth_and_declared_unit(prefix, separator):
    from AI.processors.observation_projection import source_projection_hash
    payload = {"total_orders": 10, "status_counts": {"Delivered": 4}, "api_account_ids": [7]}
    operation = "orders.status_counts"
    for depth in range(2):
        observed_at, scope = "2026-10-20T10:00:00+03:00", {"api_account_ids": [7]}
        payload = {"tool": "artifacts.read", "verified": True, "historical_observation": True,
            "fresh_read": False, "freshness": "historical_snapshot", "observed_at": observed_at, "scope": scope,
            "artifact": {"origin": {"task_id": f"prior_{depth}", "step_id": "read", "operation_id": operation},
                         "result_hash": source_projection_hash(payload), "observed_at": observed_at, "scope": scope},
            "result": payload}
        operation = "artifacts.read"
    paths = [prefix + separator.join(["result", "result", "status_counts", "Delivered"]),
             prefix + separator.join(["result", "result", "total_orders"])]
    result = calculate_observations(sources=[{"source_id": "counts", "source_step_id": "read",
        "operation_id": operation, "result": payload}], calculations=[{
            "calculation_id": "share", "operator": "percentage", "operands": [
                {"source_id": "counts", "path": path} for path in paths]}])

    assert result.success, result.data
    computed = result.data["verified_calculations"][0]
    assert computed["result_value"] == 40 and computed["unit"] == "%"
    assert [receipt["path"] for receipt in computed["operand_receipts"]] == paths
    assert [receipt["unit"] for receipt in computed["operand_receipts"]] == ["order", "order"]


@pytest.mark.parametrize("literal_present", [True, False])
def test_pointer_unit_follows_actual_literal_or_alias_value(monkeypatch, literal_present):
    from AI.runtime.contracts import AgentTool
    custom = AgentTool(name="parcels.overview", description="Parcel measures", handler=lambda: None, parameters={},
        result_schema={"type": "object", "properties": {
            "buckets.a": {"type": "number", "x-measure-unit": "literal_parcel"},
            "buckets": {"type": "object", "properties": {
                "a": {"type": "number", "x-measure-unit": "nested_parcel"}}}}})
    monkeypatch.setattr(tools, "registered_tools", lambda: {custom.name: custom})
    payload = {"buckets": {"a": 20}}
    if literal_present:
        payload["buckets.a"] = 2
    result = calculate_observations(sources=[{"source_id": "counts", "source_step_id": "read",
        "operation_id": custom.name, "result": payload}], calculations=[{
            "calculation_id": "sum", "operator": "add", "operands": [
                {"source_id": "counts", "path": "/buckets.a"}, {"source_id": "counts", "path": "/buckets.a"}]}])

    assert result.success, result.data
    computed = result.data["verified_calculations"][0]
    assert computed["result_value"] == (4 if literal_present else 40)
    assert computed["unit"] == ("literal_parcel" if literal_present else "nested_parcel")


def test_pointer_keeps_nested_key_with_literal_dots(monkeypatch):
    from AI.runtime.contracts import AgentTool
    custom = AgentTool(name="parcels.overview", description="Parcel measures", handler=lambda: None, parameters={},
        result_schema={"type": "object", "properties": {"buckets": {"type": "object", "properties": {
            "a.b": {"type": "number", "x-measure-unit": "literal_parcel"},
            "a": {"type": "object", "properties": {
                "b": {"type": "number", "x-measure-unit": "nested_parcel"}}}}}}})
    monkeypatch.setattr(tools, "registered_tools", lambda: {custom.name: custom})
    result = calculate_observations(sources=[{"source_id": "counts", "source_step_id": "read",
        "operation_id": custom.name, "result": {"buckets": {"a.b": 3, "a": {"b": 30}}}}], calculations=[{
            "calculation_id": "sum", "operator": "add", "operands": [
                {"source_id": "counts", "path": "/buckets/a.b"}, {"source_id": "counts", "path": "/buckets/a.b"}]}])

    assert result.success, result.data
    computed = result.data["verified_calculations"][0]
    assert computed["result_value"] == 6 and computed["unit"] == "literal_parcel"


def test_paged_discovery_carries_exact_search_filters_and_page_size():
    args = {"query": "orders", "domains": ["orders"], "include_manual": False, "limit": 2}
    first = discover_operation_catalog(**args)
    assert first["has_more"]
    assert first["next_page_arguments"] == {**args, "offset": 2}
    second = discover_operation_catalog(**first["next_page_arguments"])
    combined = discover_operation_catalog(**{**args, "limit": 4})
    assert [r["operation_id"] for r in first["operations"] + second["operations"]] == [r["operation_id"] for r in combined["operations"]]
    last = discover_operation_catalog(query="orders.status_counts", domains=["orders"], limit=32)
    if not last["has_more"]:
        assert last["next_page_arguments"] is None


def test_source_preview_does_not_claim_evicted_contract_is_visible():
    state = AgentSessionState(goal="Inspect tools")
    state.active_entities["model_loop"] = {"tool_menu": {"visible_tool_names": ["orders.status_counts"]}}
    state.completed_steps = [AgentTaskStep(index=1, step_id="discover", prompt="discover", status="completed",
        tool_names=["operations.discover"], result_data={"tool_result": {"operations": [
            {"operation_id": name, "exposed_tool_name": name} for name in ("orders.status_counts", "orders.snapshot")]}})]
    preview = model_loop._sources(state)[0]["result"]
    assert preview["schemas_in_tool_menu"] is False
    assert [row["contract_visible_now"] for row in preview["operations"]] == [True, False]


def test_failed_memory_path_describes_real_fields_without_substituting_a_value():
    from AI.processors.conversation_memory import read_observations
    state = AgentSessionState(goal="Inspect original result")
    state.completed_steps = [AgentTaskStep(index=1, step_id="read", prompt="read", tool_names=["orders.query"],
        status="completed", result_data={"tool_result": {"status_counts": {"Delivered": 4}, "api_key": "never-reveal"}})]
    result = read_observations(step_id="read", path="tool_result.cancel_reasons", runtime_context={"state": state})
    assert not result.success and result.data["reason"] == "stored_result_path_missing"
    assert result.data["available_keys"] == ["status_counts"]
    assert result.data["repair_arguments"] == {"step_id": "read", "path": "tool_result", "offset": 0, "limit": 20}
    assert "value" not in result.data and "never-reveal" not in json.dumps(result.data)


def test_model_chosen_discovery_count_and_calculation_complete_with_one_business_read(population):
    db, oracle = population
    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        def __init__(self):
            self.calls = iter([
                {"mode": "tool", "tool": "operations.discover", "arguments": {"query": "orders.status_counts", "limit": 1}},
                {"mode": "tool", "tool": "orders.status_counts", "arguments": {"period": "all"}},
                {"mode": "tool", "tool": "operations.discover", "arguments": {"query": "analysis.calculate", "limit": 1}},
                {"mode": "tool", "tool": "analysis.calculate", "arguments": {"sources": [{
                    "source_id": "counts", "source_step_id": "call_2", "operation_id": "orders.status_counts",
                    "result": {"$from_step": "call_2", "path": "tool_result"}}], "calculations": [expression()]}},
                "Durum dağılımını mevcut toplam ve teslim edilen sayısıyla hesapladım."])
        def invoke_tools(self, prompt, *, tools):
            value = next(self.calls)
            return json.dumps(value) if isinstance(value, dict) else value
    result = model_loop.run_model_loop("Siparişlerin durumlarını ve teslim edilen oranını göster", client=Model(), db_name=db)
    assert result.success
    reads = result.data["direct_tool_calls"]
    assert [row["tool"] for row in reads] == ["operations.discover", "orders.status_counts", "operations.discover", "analysis.calculate"]
    assert all(row["success"] for row in result.data["direct_tool_results"])
    assert result.data["direct_tool_results"][1]["data"]["status_counts"] == oracle
    assert result.data["direct_tool_results"][-1]["data"]["verified"]
