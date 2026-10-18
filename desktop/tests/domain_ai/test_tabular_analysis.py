from copy import deepcopy

import pytest

from AI.processors.analysis_operations import calculate_observations
from AI.processors.tabular_analysis import analyze_observation_table


def _source(rows, coverage="complete"):
    return [{"source_id": "attached", "source_step_id": "file_read", "operation_id": "files.read",
             "result": {"rows": rows, "data_coverage": {"status": coverage}}}]


def test_grouped_sums_keep_different_currencies_and_nulls_separate():
    source = _source([{"sku": "A", "revenue": 120, "currency": "TRY"},
                      {"sku": "B", "revenue": 80, "currency": "TRY"},
                      {"sku": "C", "revenue": None, "currency": "TRY"},
                      {"sku": "D", "revenue": 30, "currency": "USD"}])
    result = analyze_observation_table(sources=source, source_id="attached", rows_path="rows",
                                      group_by=["currency"], measures=[{"name": "revenue", "operator": "sum", "path": "revenue", "unit_path": "currency"}])
    assert result.success, result.data
    assert result.data["source_row_count"] == 4 and result.data["group_count"] == 2
    try_metric = result.data["rows"][0]["metrics"]["revenue"]
    assert try_metric["value"] == 200 and try_metric["unit"] == "TRY"
    assert try_metric["null_count"] == 1 and try_metric["observed_value_count"] == 2
    assert result.data["rows"][1]["metrics"]["revenue"]["value"] == 30
    assert result.data["data_coverage"]["status"] == "complete"
    source[0]["result"]["rows"][0]["revenue"] = 999
    assert try_metric["value"] == 200


def test_same_measure_cannot_add_different_currencies_without_grouping():
    result = analyze_observation_table(sources=_source([{"amount": 400, "currency": "TRY"}, {"amount": 30, "currency": "USD"}]),
                                      source_id="attached", rows_path="rows",
                                      measures=[{"name": "money", "operator": "sum", "path": "amount", "unit_path": "currency"}])
    assert not result.success and result.data["reason"] == "table_incompatible_units_group_by_currency_or_unit"


def test_explicit_csv_lexical_format_is_exact_and_carries_conversion_proof():
    source = _source([{"column_1": "1.234,50", "column_2": "TRY"}, {"column_1": "0,10", "column_2": "TRY"}])
    result = analyze_observation_table(sources=source, source_id="attached", rows_path="rows", measures=[{
        "name": "total", "operator": "sum", "path": "column_1", "unit_path": "column_2", "number_format": "decimal_comma_group_dot"}])
    assert result.success, result.data
    assert result.data["rows"][0]["metrics"]["total"]["exact_value"] == "1234.60"
    assert result.data["conversion_receipts"][0] == {
        "source_row_index": 0, "source_path": "column_1", "original": "1.234,50",
        "parsed_decimal": "1234.50", "number_format": "decimal_comma_group_dot"}
    assert source[0]["result"]["rows"][0]["column_1"] == "1.234,50"


@pytest.mark.parametrize("value", ["1,23.4", "1.2.3", "=SUM(A1:A9)", "NaN", "12 TRY", "1,234"])
def test_ambiguous_or_instruction_like_strings_do_not_become_numbers(value):
    result = analyze_observation_table(sources=_source([{"value": value}]), source_id="attached", rows_path="rows",
                                      measures=[{"name": "sum", "operator": "sum", "path": "value", "number_format": "decimal_dot"}])
    assert not result.success and result.data["reason"] == "table_numeric_format_mismatch"


def test_string_fields_require_explicit_format_and_unspecified_units_are_honest():
    source = _source([{"value": "200"}])
    measure = {"name": "sum", "operator": "sum", "path": "value"}
    assert analyze_observation_table(sources=source, source_id="attached", rows_path="rows", measures=[measure]).success is False
    measure["number_format"] = "decimal_dot"
    result = analyze_observation_table(sources=source, source_id="attached", rows_path="rows", measures=[measure])
    assert result.success
    assert result.data["rows"][0]["metrics"]["sum"]["unit"] is None
    assert result.data["rows"][0]["metrics"]["sum"]["unit_basis"] == "unspecified"


def test_counts_zero_and_all_null_amounts_have_distinct_evidence():
    result = analyze_observation_table(sources=_source([]), source_id="attached", rows_path="rows", measures=[
        {"name": "records", "operator": "count"}, {"name": "sum", "operator": "sum", "path": "amount"}])
    assert result.success
    assert result.data["rows"][0]["metrics"]["records"]["value"] == 0
    assert result.data["rows"][0]["metrics"]["sum"]["value"] is None
    null_result = analyze_observation_table(sources=_source([{"amount": None}]), source_id="attached", rows_path="rows", measures=[
        {"name": "average", "operator": "average", "path": "amount"}])
    assert null_result.data["rows"][0]["metrics"]["average"]["value"] is None
    assert null_result.data["rows"][0]["metrics"]["average"]["null_count"] == 1


def test_partial_input_remains_partial_after_aggregation():
    result = analyze_observation_table(sources=_source([{"amount": 200}], "partial"), source_id="attached", rows_path="rows",
                                      measures=[{"name": "sum", "operator": "sum", "path": "amount"}])
    assert result.success and result.data["data_coverage"]["status"] == "partial"


def test_verified_group_totals_can_feed_later_source_bound_arithmetic():
    table = analyze_observation_table(sources=_source([{"amount": 120, "currency": "TRY"}, {"amount": 80, "currency": "TRY"}]),
                                     source_id="attached", rows_path="rows", measures=[
                                         {"name": "sum", "operator": "sum", "path": "amount", "unit_path": "currency"}]).data
    sources = [{"source_id": "table", "source_step_id": "aggregate_read", "operation_id": "analysis.table", "result": table},
               {"source_id": "previous", "source_step_id": "prior_read", "operation_id": "orders.revenue_total", "result": {"total": 100, "currency": "TRY"}}]
    result = calculate_observations(sources=sources, calculations=[{"calculation_id": "change", "operator": "subtract", "operands": [
        {"source_id": "table", "path": "rows.0.metrics.sum.value"}, {"source_id": "previous", "path": "total"}]}])
    assert result.success, result.data
    assert result.data["verified_calculations"][0]["result"] == "100.00"
    assert result.data["verified_calculations"][0]["business_relationship_verified"] is False


def test_final_table_evidence_recomputes_provenance_and_rejects_rehashed_wrong_total():
    from AI.processors.session_state import AgentSessionState, AgentTaskStep
    from AI.processors.observation_analysis_evidence import verified_observation_tables
    from AI.processors.response_verifier import response_evidence_projection

    source = _source([{"amount": 120, "currency": "TRY"}, {"amount": 80, "currency": "TRY"}])
    result = analyze_observation_table(sources=source, source_id="attached", rows_path="rows", measures=[
        {"name": "sum", "operator": "sum", "path": "amount", "unit_path": "currency"}])
    state = AgentSessionState(goal="Sum the attached rows", active_domain="general")
    state.completed_steps = [
        AgentTaskStep(index=1, step_id="file_read", prompt="Read", status="completed", verification_status="observed",
                      tool_names=["files.read"], result_data={"tool_result": source[0]["result"]}),
        AgentTaskStep(index=2, step_id="aggregate", prompt="Calculate", status="completed", verification_status="observed",
                      tool_names=["analysis.table"], result_data={"tool_result": result.data}),
    ]
    assert verified_observation_tables(state)[0]["rows"][0]["metrics"]["sum"]["value"] == 200
    assert response_evidence_projection(state)["verified_table_analyses"] == [result.data]
    from AI.processors.observation_projection import source_projection_hash
    result.data["rows"][0]["metrics"]["sum"]["value"] = 999
    result.data["evidence_hash"] = source_projection_hash({key: value for key, value in result.data.items() if key != "evidence_hash"})
    assert verified_observation_tables(state) == []
