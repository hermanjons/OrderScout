"""Projection failures carry observed structure through the real task runtime."""
from copy import deepcopy
import json

import pytest

from AI.processors import report_builder, task_store, tools
from AI.processors.business_acceptance_fixtures import seed_business_fixture
from AI.processors.observation_projection import source_projection_hash
from AI.processors.task_runtime import run_agent_task


@pytest.fixture
def observed_sales(tmp_path):
    database = str(tmp_path / "business.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    read = tools.available_tools()["orders.item_sales_summary"].handler(
        period="all", group_by="product", limit=100, api_account_ids=[101], db_name=database,
    )
    assert read.success, read.message
    assert read.data["rows"][0]["product_name"]
    return database, read.data


def _source(data):
    return {"source_id": "sales", "source_step_id": "actual_sales",
            "operation_id": "orders.item_sales_summary", "result": data}


def _sheet(path="product", rows_path="rows", data_type="string"):
    return {"name": "Products", "source_id": "sales", "rows_path": rows_path,
            "columns": [{"key": "product", "label": "Product", "source_path": path, "data_type": data_type}]}


def _paths(shape):
    return {row["path"]: row["type"] for row in shape["paths"]}


def test_dictionary_projection_is_explicit_preserves_null_zero_and_legacy_hash():
    data = {"counts": {"Pending": 4, "Empty": 0, "Unknown": None}}
    source = _source(data)
    sheet = {"name": "Counts", "source_id": "sales", "rows_path": "counts", "rows_mode": "object_entries",
             "columns": [{"key": "status", "label": "Status", "source_path": "key", "data_type": "string"},
                         {"key": "count", "label": "Count", "source_path": "value", "data_type": "integer"}]}
    result = report_builder.build_observation_report_snapshot(title="Counts", sources=[source], sheets=[sheet])
    assert result.sheets[0].rows == (("Pending", 4), ("Empty", 0), ("Unknown", None))
    assert result.metadata["projections"][0]["rows_mode"] == "object_entries"
    assert result.metadata["domain_calculations_performed"] is False
    legacy = {"name": "Counts", "source_id": "sales", "rows_path": "counts", "columns": [
        {"key": "pending", "label": "Pending", "source_path": "Pending", "data_type": "integer"}]}
    a = report_builder.build_observation_report_snapshot(title="Counts", sources=[source], sheets=[legacy])
    b = report_builder.build_observation_report_snapshot(title="Counts", sources=[source], sheets=[{**legacy, "rows_mode": "records"}])
    assert a.content_hash == b.content_hash
    assert "rows_mode" not in a.metadata["projections"][0]
    with pytest.raises(ValueError, match="report_object_entries_requires_string_key_mapping"):
        report_builder.build_observation_report_snapshot(title="Invalid", sources=[_source({"counts": []})], sheets=[sheet])


def test_actual_canonical_missing_product_rejects_with_safe_exact_source_structure(observed_sales):
    _, data = observed_sales
    with pytest.raises(report_builder.ReportProjectionError) as failure:
        report_builder.build_observation_report_snapshot(title="Read only", sources=[_source(data)], sheets=[_sheet()])
    assert str(failure.value) == "observation_projection_path_missing:product"
    diagnostic = failure.value.diagnostic
    assert diagnostic["reason_code"] == str(failure.value)
    assert diagnostic["source_result_hash"] == source_projection_hash(data)
    assert diagnostic["source_step_id"] == "actual_sales" and diagnostic["operation_id"] == "orders.item_sales_summary"
    assert (diagnostic["projection_kind"], diagnostic["sheet_index"], diagnostic["row_index"], diagnostic["column_index"]) == ("column", 0, 0, 0)
    assert _paths(diagnostic["projection_shape"])["/product_name"] == "string"
    assert _paths(diagnostic["projection_shape"])["/quantity"] == "integer"
    assert "/product" not in _paths(diagnostic["projection_shape"])
    assert _paths(diagnostic["source_shape"])["/rows/0/product_name"] == "string"
    assert data["rows"][0]["product_name"] not in json.dumps(diagnostic, ensure_ascii=False)
    diagnostic["source_shape"]["paths"].clear()
    assert failure.value.diagnostic["source_shape"]["paths"]  # independent immutable exception evidence
    result = tools.available_tools()["reports.build_snapshot"].handler(title="Read only", sources=[_source(data)], sheets=[_sheet()])
    assert not result.success
    assert result.data["reason_codes"] == ["observation_projection_path_missing:product"]
    assert result.data["projection_diagnostic"] == failure.value.diagnostic
    assert "report_snapshot" not in result.data and "action" not in result.data


def test_correct_observed_product_name_projects_exact_values_without_aliasing(observed_sales):
    _, data = observed_sales
    snapshot = report_builder.build_observation_report_snapshot(
        title="Native fields", sources=[_source(data)], sheets=[_sheet("product_name")],
    )
    assert snapshot.sheets[0].rows == tuple((row["product_name"],) for row in data["rows"])
    assert snapshot.metadata["source_receipts"][0]["source_result_hash"] == source_projection_hash(data)
    assert snapshot.metadata["domain_calculations_performed"] is False


@pytest.mark.parametrize("rows_path", ["tool_result.rows", "not_observed"])
def test_rows_path_failure_describes_bound_root_and_relative_paths(observed_sales, rows_path):
    _, data = observed_sales
    failed = tools.reports_build_snapshot(title="Read", sources=[_source(data)], sheets=[_sheet("product_name", rows_path)])
    assert not failed.success
    assert failed.data["reason_codes"] == [f"observation_projection_path_missing:{rows_path}"]
    diagnostic = failed.data["projection_diagnostic"]
    assert diagnostic["projection_kind"] == "rows" and diagnostic["row_index"] is None
    assert _paths(diagnostic["source_shape"])["/rows"] == "array"
    assert "tool_result" not in _paths(diagnostic["source_shape"])
    assert "relative_to_bound_source_result" in diagnostic["path_guidance"]["rows_path"]
    assert "relative_to_selected_row" == diagnostic["path_guidance"]["source_path"]


def test_type_mismatch_stays_fail_closed_and_diagnostic_contains_types_not_values(observed_sales):
    _, data = observed_sales
    failed = tools.reports_build_snapshot(title="Read", sources=[_source(data)], sheets=[_sheet("product_name", data_type="number")])
    assert not failed.success
    assert failed.data["reason_codes"] == ["report_column_source_type_mismatch:product_name:number"]
    assert _paths(failed.data["projection_diagnostic"]["projection_shape"])["/product_name"] == "string"
    assert data["rows"][0]["product_name"] not in json.dumps(failed.data["projection_diagnostic"])


def test_observed_scalar_cannot_be_selected_as_record_rows(observed_sales):
    _, data = observed_sales
    failed = tools.reports_build_snapshot(title="Read", sources=[_source(data)], sheets=[_sheet(rows_path="total_quantity")])
    assert not failed.success and failed.data["reason_codes"] == ["report_source_rows_must_be_records"]
    assert failed.data["projection_diagnostic"]["projection_shape"]["paths"] == [{"path": "", "type": "integer"}]


def test_missing_field_in_later_row_reports_that_row_and_never_borrows_first_row(observed_sales):
    _, original = observed_sales
    data = deepcopy(original)
    assert len(data["rows"]) >= 2
    del data["rows"][1]["product_name"]
    failed = tools.reports_build_snapshot(title="Read", sources=[_source(data)], sheets=[_sheet("product_name")])
    assert not failed.success and failed.data["projection_diagnostic"]["row_index"] == 1
    assert "/product_name" not in _paths(failed.data["projection_diagnostic"]["projection_shape"])
    assert "report_snapshot" not in failed.data


def test_large_diagnostic_is_bounded_and_excludes_scalar_values_and_credentials():
    canary = "PRIVATE_OBSERVED_VALUE_DO_NOT_ECHO"
    payload = {"rows": [{"nested": {"inner": {"deep": {"value": canary}}},
                         "api_token": {"private_name": canary},
                         **{f"field_{index}": canary for index in range(400)}}]}
    payload["rows"][0]["/long/" + "z" * 300] = canary
    failed = tools.reports_build_snapshot(title="Bounded", sources=[_source(payload)], sheets=[_sheet()])
    assert not failed.success
    diagnostic = failed.data["projection_diagnostic"]
    for shape in (diagnostic["source_shape"], diagnostic["projection_shape"]):
        assert len(shape["paths"]) <= 96 and shape["truncated"] is True
        assert all(len(row["path"]) <= 256 for row in shape["paths"])
    encoded = json.dumps(diagnostic)
    assert canary not in encoded and "api_token" not in encoded and "private_name" not in encoded
    assert len(encoded) < 20_000


def test_non_projection_error_does_not_publish_arbitrary_exception_diagnostic():
    error = ValueError("ordinary")
    error.diagnostic = {"secret": "not a projection receipt"}
    assert report_builder.projection_failure_diagnostic(error) == {}


def test_real_task_runtime_persists_canonical_projection_failure_without_output_or_approval(observed_sales, tmp_path):
    database, _ = observed_sales
    checkpoints = tmp_path / "checkpoints"
    plan = {"steps": [
        {"id": "actual_sales", "operation_id": "orders.item_sales_summary",
         "arguments": {"period": "all", "group_by": "product", "limit": 100, "api_account_ids": [101]},
         "depends_on": [], "objective": "Read Pilot Ana product sales", "expected_evidence": ["rows", "source_snapshot_hash"]},
        {"id": "actual_report", "operation_id": "reports.build_snapshot",
         "arguments": {"title": "Products", "sources": [_source({"$from_step": "actual_sales", "path": "tool_result"})],
                       "sheets": [_sheet()]},
         "depends_on": ["actual_sales"], "objective": "Project actual observed product fields", "expected_evidence": ["report_snapshot"]},
    ]}
    planned = False

    def planner(prompt):
        nonlocal planned
        if prompt.startswith("GoalPlan observation"):
            return json.dumps({"decision": "continue", "reason": "Run the declared remaining projection"})
        if "agent task final cevabi yaz." in prompt:
            return ""
        if planned:
            return json.dumps({"steps": [], "reason": "Keep the exact failed projection for inspection"})
        planned = True
        return json.dumps(plan)

    result = run_agent_task(
        "Create a custom report with all Pilot Ana product sales observations in selected columns.",
        domain="general", planner_client=planner, db_name=database, persist=True,
        task_store_root=str(checkpoints), max_steps=24, max_replans=1,
        turn_interpretation={"mode": "inspect", "intent_kind": "data_read", "domain": "general", "valid": True,
                             "request_shape": "broad_analysis", "objective": "Read and project Pilot Ana product sales",
                             "requested_fields": ["scope"], "requires_clarification": False},
    )
    state = result.data["state"]
    assert state["status"] == "failed", state
    assert len(state["completed_steps"]) == 2
    actual = state["completed_steps"][0]
    assert actual["status"] == "completed" and actual["tool_names"] == ["orders.item_sales_summary"]
    assert actual["result_data"]["tool_result"]["account_scopes"][0]["api_account_id"] == 101
    failed = state["completed_steps"][1]
    assert failed["status"] == "failed" and failed["tool_names"] == ["reports.build_snapshot"]
    receipt = failed["result_data"]["tool_result"]
    assert receipt["reason_codes"] == ["observation_projection_path_missing:product"]
    assert receipt["projection_diagnostic"]["source_result_hash"] == source_projection_hash(actual["result_data"]["tool_result"])
    assert _paths(receipt["projection_diagnostic"]["projection_shape"])["/product_name"] == "string"
    assert failed["result_data"]["dependency_bindings"] == {"sources[0].result": "actual_sales:tool_result"}
    assert state["pending_actions"] == [] and state["action_history"] == []
    persisted = task_store.load_agent_task_state(state["session_id"], root=checkpoints)
    assert persisted.completed_steps[1].result_data["tool_result"] == receipt
    assert not list(tmp_path.rglob("*.xlsx"))


def test_report_parameter_contract_explains_relative_paths_and_empty_root():
    parameters = tools.available_tools()["reports.build_snapshot"].parameters
    sheet = parameters["properties"]["sheets"]["items"]["properties"]
    assert "without another tool_result prefix" in sheet["rows_path"]["description"]
    assert "empty string" in sheet["rows_path"]["description"]
    column = sheet["columns"]["items"]["properties"]
    assert "relative to each selected row" in column["source_path"]["description"]
