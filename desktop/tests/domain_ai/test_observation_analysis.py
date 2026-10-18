"""Independent arithmetic and provenance cases for the model-neutral tool."""
from copy import deepcopy
from decimal import Decimal

import pytest

from AI.processors.analysis_operations import calculate_observations
from AI.processors.observation_projection import source_projection_hash


def _source(source_id, amount, *, currency="TRY", account_id=101, period="last_7_days"):
    return {"source_id": source_id, "source_step_id": f"read_{source_id}",
            "operation_id": "orders.revenue_total", "result": {
                "total": amount, "currency": currency, "count": 3 if source_id == "current" else 2,
                "account_ids": [account_id], "environment": "stage", "period": period,
            }}


def _difference(sources, **overrides):
    expression = {"calculation_id": "revenue_change", "operator": "subtract",
                  "operands": [{"source_id": "current", "path": "total"},
                               {"source_id": "previous", "path": "total"}], **overrides}
    return calculate_observations(sources=sources, calculations=[expression])


def test_period_difference_uses_decimal_arithmetic_and_receipts_cover_exact_sources():
    sources = [_source("current", 3000), _source("previous", 800, period="previous_7_days")]
    result = _difference(sources)
    assert result.success, result.data
    payload = result.data
    calculation = payload["verified_calculations"][0]
    assert calculation["result"] == "2200.00" and calculation["result_value"] == 2200
    assert calculation["unit"] == "TRY" and calculation["result_kind"] == "amount"
    assert calculation["operands"] == ["3000", "800"]
    assert calculation["operand_receipts"][0]["value"] == 3000
    assert calculation["source_receipts"][1]["period"] == {"period": "previous_7_days"}
    assert calculation["source_receipts"][0]["source_result_hash"] == source_projection_hash(sources[0]["result"])
    assert payload["evidence_hash"] == source_projection_hash({key: value for key, value in payload.items() if key != "evidence_hash"})
    assert calculation["business_relationship_verified"] is False
    sources[0]["result"]["total"] = 1
    assert calculation["result_value"] == 2200


def test_percentage_is_relative_ratio_and_comparison_is_separate_boolean_evidence():
    sources = [_source("current", 3000), _source("previous", 800)]
    result = calculate_observations(sources=sources, calculations=[{
        "calculation_id": "relative_revenue", "operator": "percentage",
        "operands": [{"source_id": "current", "path": "total"}, {"source_id": "previous", "path": "total"}],
    }], comparisons=[{"comparison_id": "increased", "operator": "greater_than",
                     "left": {"source_id": "current", "path": "total"},
                     "right": {"source_id": "previous", "path": "total"}}])
    assert result.success, result.data
    assert result.data["verified_calculations"][0]["result"] == "375.00"
    assert result.data["verified_calculations"][0]["unit"] == "%"
    comparison = result.data["verified_comparisons"][0]
    assert comparison["holds"] is True and comparison["result_kind"] == "boolean"


@pytest.mark.parametrize("change,reason", [
    ("currency", "analysis_incompatible_units"),
    ("account", "analysis_source_entity_scope_mismatch"),
    ("environment", "analysis_source_entity_scope_mismatch"),
    ("null", "analysis_operand_not_observed_numeric"),
    ("string", "analysis_operand_not_observed_numeric"),
    ("non_finite", "observation_projection_non_finite_number"),
    ("missing", "observation_projection_path_missing:total"),
])
def test_incompatible_or_missing_observations_do_not_create_calculation_evidence(change, reason):
    sources = [_source("current", 3000), _source("previous", 800)]
    previous = sources[1]["result"]
    if change == "currency":
        previous["currency"] = "USD"
    elif change == "account":
        previous["account_ids"] = [102]
    elif change == "environment":
        previous["environment"] = "production"
    elif change == "null":
        previous["total"] = None
    elif change == "string":
        previous["total"] = "800"
    elif change == "non_finite":
        previous["total"] = float("nan")
    else:
        previous.pop("total")
    result = _difference(sources)
    assert not result.success and result.data["reason"] == reason and result.data["verified"] is False
    if change in {"null", "string", "missing"}:
        assert result.data["failed_operand"] == {"source_id": "previous", "source_step_id": "read_previous",
                                                  "operation_id": "orders.revenue_total", "path": "total"}
        assert "actual" in result.data["repair_policy"]


def test_literal_operands_and_identifiers_are_not_business_measures():
    sources = [_source("current", 3000), _source("previous", 800)]
    result = _difference(sources, operands=[{"source_id": "current", "path": "total"}, {"value": 800}])
    assert not result.success and result.data["reason"] == "analysis_operand_requires_source_reference"
    sources[0]["result"]["record_id"] = 900
    sources[1]["result"]["record_id"] = 901
    result = _difference(sources, operands=[{"source_id": "current", "path": "record_id"},
                                         {"source_id": "previous", "path": "record_id"}])
    assert not result.success and result.data["reason"] == "analysis_measure_unit_unknown:record_id"


def test_observed_zero_is_valid_but_division_by_zero_is_not():
    sources = [_source("current", 0), _source("previous", 0)]
    assert _difference(sources).data["verified_calculations"][0]["result"] == "0.00"
    result = _difference(sources, operator="divide")
    assert not result.success and result.data["reason"] == "analysis_division_by_zero"


def test_divide_operator_retains_its_identity_when_output_is_requested_as_percentage():
    sources = [_source("current", 3000), _source("previous", 800)]
    calculated = _difference(sources, operator="divide", result_unit="percentage")
    assert calculated.success
    row = calculated.data["verified_calculations"][0]
    assert row["operator"] == "divide" and row["result"] == "375.00"
    assert row["unit"] == "%" and row["result_kind"] == "percentage"
    assert row["quantity_scaling"]["result_scale"] == "0.01"
    state = _analysis_state()
    state.completed_steps[-1].result_data["tool_result"] = calculated.data
    from AI.processors.observation_analysis_evidence import verified_observation_calculations
    assert verified_observation_calculations(state)[0]["result"] == "375.00"
    incompatible = _difference(sources, operator="subtract", result_unit="percentage")
    assert not incompatible.success and incompatible.data["reason"] == "analysis_result_unit_incompatible"


def test_nested_currency_maps_and_quantity_dimensions_preserve_units():
    sources = [{"source_id": "stock", "source_step_id": "stock_read", "operation_id": "stock.inventory_overview",
                "result": {"stock_value_by_currency": [{"currency": "TRY", "amount": 400}],
                           "balance_by_unit": [{"unit": "adet", "balance": 4}]}},
               {"source_id": "money", "source_step_id": "cashflow_read", "operation_id": "finance.cashflow_summary",
                "result": {"income_by_currency": {"TRY": Decimal("0.10")},
                           "currency_totals": [{"currency": "TRY", "combined_net": Decimal("0.20")} ]}}]
    result = calculate_observations(sources=sources, calculations=[{
        "calculation_id": "exact_sum", "operator": "add", "operands": [
            {"source_id": "money", "path": "/income_by_currency/TRY"},
            {"source_id": "money", "path": "currency_totals.0.combined_net"} ]},
        {"calculation_id": "value_per_unit", "operator": "divide", "operands": [
            {"source_id": "stock", "path": "stock_value_by_currency.0.amount"},
            {"source_id": "stock", "path": "balance_by_unit.0.balance"} ]}])
    assert result.success, result.data
    assert result.data["verified_calculations"][0]["result"] == "0.30"
    unit_value = result.data["verified_calculations"][1]
    assert unit_value["result"] == "100.00" and unit_value["unit"] == "TRY/adet"
    assert unit_value["result_kind"] == "amount_per_quantity"


def test_canonical_orders_summary_count_and_explicit_percentage_unit_are_compatible():
    from AI.processors.observation_analysis_evidence import verified_observation_calculations
    from AI.processors.session_state import AgentSessionState, AgentTaskStep

    sources = [_source("current", 3000), _source("previous", 800)]
    for source in sources:
        source["operation_id"] = "orders.summary"
        source["result"]["total_orders"] = source["result"].pop("count")
    calculated = calculate_observations(sources=sources, calculations=[{
        "calculation_id": "current_as_percent_of_previous", "operator": "percentage", "result_unit": "percentage",
        "operands": [{"source_id": "current", "path": "total"}, {"source_id": "previous", "path": "total"}],
    }, {"calculation_id": "orders_difference", "operator": "subtract", "operands": [
        {"source_id": "current", "path": "total_orders"}, {"source_id": "previous", "path": "total_orders"},
    ]}])
    assert calculated.success, calculated.data
    assert calculated.data["verified_calculations"][0]["result"] == "375.00"
    assert calculated.data["verified_calculations"][1]["result"] == "1.00"
    assert calculated.data["verified_calculations"][1]["unit"] == "order"
    state = AgentSessionState(goal="Compare periods", active_domain="general")
    for source in sources:
        state.completed_steps.append(AgentTaskStep(
            index=len(state.completed_steps) + 1, step_id=source["source_step_id"], prompt="Read",
            status="completed", verification_status="observed", tool_names=[source["operation_id"]],
            result_data={"tool_result": source["result"]},
        ))
    state.completed_steps.append(AgentTaskStep(index=3, step_id="calculate", prompt="Calculate", status="completed",
                                              verification_status="observed", tool_names=["analysis.calculate"],
                                              result_data={"tool_result": calculated.data}))
    assert [row["result"] for row in verified_observation_calculations(state)] == ["375.00", "1.00"]


def test_generic_record_count_does_not_acquire_an_order_unit():
    result = calculate_observations(sources=[{
        "source_id": "file", "source_step_id": "read", "operation_id": "files.read",
        "result": {"count": 4, "row_count": 3},
    }], calculations=[{"calculation_id": "record_difference", "operator": "subtract", "operands": [
        {"source_id": "file", "path": "count"}, {"source_id": "file", "path": "row_count"},
    ]}])
    assert result.success, result.data
    assert result.data["verified_calculations"][0]["unit"] == "record"


@pytest.mark.parametrize("precision", [True, 2.5, "2", -1, 7])
def test_precision_does_not_silently_truncate_invalid_values(precision):
    result = _difference([_source("current", 3000), _source("previous", 800)], precision=precision)
    assert not result.success and result.data["reason"] == "analysis_invalid_precision"


def test_expression_evidence_changes_when_authoritative_source_changes_even_for_equal_result():
    sources = [_source("current", 3000), _source("previous", 800)]
    first = _difference(sources).data
    changed = deepcopy(sources)
    changed[0]["result"]["period"] = "last_30_days"
    second = _difference(changed).data
    assert first["verified_calculations"][0]["result"] == second["verified_calculations"][0]["result"]
    assert first["evidence_hash"] != second["evidence_hash"]


def _analysis_state():
    from AI.processors.session_state import AgentSessionState, AgentTaskStep

    sources = [_source("current", 3000), _source("previous", 800)]
    state = AgentSessionState(goal="Compare revenue", active_domain="general")
    for source in sources:
        state.completed_steps.append(AgentTaskStep(
            index=len(state.completed_steps) + 1, step_id=source["source_step_id"], prompt="Read",
            status="completed", verification_status="observed", tool_names=[source["operation_id"]],
            result_data={"tool_result": source["result"]},
        ))
    state.completed_steps.append(AgentTaskStep(
        index=3, step_id="analysis", prompt="Calculate", status="completed", verification_status="observed",
        tool_names=["analysis.calculate"], result_data={"tool_result": _difference(sources).data},
    ))
    return state


def test_final_evidence_revalidates_original_sources_and_core_arithmetic():
    from AI.processors.observation_analysis_evidence import verified_observation_calculations
    from AI.processors.response_verifier import verified_derived_calculations

    state = _analysis_state()
    projected = verified_observation_calculations(state)
    assert projected[0]["result"] == "2200.00"
    assert projected[0]["operands"][0]["value"] == 3000
    assert projected[0]["operands"][0]["source_step_id"] == "read_current"
    assert verified_derived_calculations(state) == projected


def test_independent_calculate_steps_all_remain_available_to_goal_completion():
    from AI.processors.observation_analysis_evidence import verified_observation_calculations
    from AI.processors.session_state import AgentTaskStep

    state = _analysis_state()
    sources = [_source("current", 3000), _source("previous", 800)]
    second = _difference(sources, calculation_id="revenue_ratio", operator="divide").data
    state.completed_steps.append(AgentTaskStep(
        index=4, step_id="second_analysis", prompt="Divide", status="completed", verification_status="observed",
        tool_names=["analysis.calculate"], result_data={"tool_result": second},
    ))
    projected = verified_observation_calculations(state)
    assert [(row["operator"], row["result"]) for row in projected] == [("subtract", "2200.00"), ("divide", "3.75")]


@pytest.mark.parametrize("mutation", ["source_value", "source_operation", "result", "operand_receipt", "core_hash", "currency", "kind"])
def test_final_projection_rejects_rewritten_source_or_calculation_receipts(mutation):
    from AI.processors.observation_analysis_evidence import verified_observation_calculations

    state = _analysis_state()
    payload = state.completed_steps[-1].result_data["tool_result"]
    calculation = payload["verified_calculations"][0]
    if mutation == "source_value":
        state.completed_steps[0].result_data["tool_result"]["total"] = 9000
    elif mutation == "source_operation":
        state.completed_steps[0].tool_names = ["orders.cancelled_count"]
    elif mutation == "result":
        calculation["result"] = "3000.00"
    elif mutation == "operand_receipt":
        calculation["operand_receipts"][0]["value"] = 9000
    elif mutation == "core_hash":
        calculation["arithmetic_evidence_hash"] = "rehashed-fake-core"
    elif mutation == "currency":
        calculation["unit"] = "USD"
        calculation["operand_receipts"][0]["unit"] = "USD"
    else:
        calculation["result_kind"] = "count"
    # Rehashing caller-provided metadata cannot forge authoritative sources or
    # arithmetic; this also tests persisted state that has been tampered with.
    calculation["evidence_hash"] = source_projection_hash({key: value for key, value in calculation.items() if key != "evidence_hash"})
    payload["evidence_hash"] = source_projection_hash({key: value for key, value in payload.items() if key != "evidence_hash"})
    assert verified_observation_calculations(state) == []
