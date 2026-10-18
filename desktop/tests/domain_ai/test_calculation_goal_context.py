"""Arithmetic alignment has separate ownership from other completed goal reads."""
import json
import pytest

from AI.processors import tools
from AI.processors.analysis_operations import calculate_observations
from AI.processors.business_acceptance_fixtures import seed_business_fixture
from AI.processors.observation_analysis_evidence import verified_observation_calculations
from AI.processors.semantic_verifier import _calculation_goal_context, verify_calculation_goal_semantics
from AI.processors.session_state import AgentSessionState, AgentTaskStep


def _add(state, identity, operation, result):
    state.completed_steps.append(AgentTaskStep(index=len(state.completed_steps) + 1, step_id=identity,
        prompt="Observe", status="completed", verification_status="observed", tool_names=[operation],
        result_data={"tool_result": result}))


def test_cross_domain_read_receipts_are_visible_without_becoming_formula_requirements(tmp_path):
    database = tmp_path / "business.sqlite3"
    seed_business_fixture(str(database), isolation_root=tmp_path)
    state = AgentSessionState(goal="Compare sales and research inventory value and registered finance movements", active_domain="general")
    sources = []
    for identity, amount in (("current", 3000), ("prior", 800)):
        observed = {"estimated_revenue": amount, "currency": "TRY", "account_scopes": [{"api_account_id": 101}]}
        _add(state, identity, "orders.summary", observed)
        sources.append({"source_id": identity, "source_step_id": identity, "operation_id": "orders.summary", "result": observed})
    calculation = calculate_observations(sources=sources, calculations=[{"calculation_id": "change", "operator": "subtract",
        "operands": [{"source_id": "current", "path": "estimated_revenue"}, {"source_id": "prior", "path": "estimated_revenue"}]}])
    assert calculation.success
    _add(state, "calculate", "analysis.calculate", calculation.data)
    for identity, operation in (("inventory", "stock.inventory_overview"), ("finance", "finance.cashflow_summary")):
        result = tools.available_tools()[operation].handler(db_name=str(database))
        assert result.success, result.message
        _add(state, identity, operation, result.data)
    verified = verified_observation_calculations(state)
    prompts = []
    def verifier(prompt):
        prompts.append(prompt)
        evidence = json.loads(prompt.split("Evidence: ", 1)[1])
        operations = {row["operation_id"] for row in evidence["completed_read_observations"]}
        assert {"stock.inventory_overview", "finance.cashflow_summary"}.issubset(operations)
        assert evidence["whole_goal_completion_checked_separately"] is True
        assert len(evidence["calculations"]) == 1
        return json.dumps({"verdict": "allow", "objective_aligned": True, "requested_calculations_complete": True,
            "scope_aligned": True, "periods_aligned": True, "units_aligned": True, "comparison_satisfied": False,
            "accepted_evidence_hashes": [verified[0]["evidence_hash"]], "requested_calculation_count": 1,
            "requested_result_kinds": ["amount"], "period_relations": [], "reason": "Only the sales change is arithmetic."})
    assert verify_calculation_goal_semantics(state, verifier_client=verifier)["allowed"]
    assert len(prompts) == 1


def test_failed_unverified_and_effectful_steps_never_supply_completed_read_coverage_or_private_values():
    state = AgentSessionState(goal="Compare", active_domain="general")
    raw = {"stock_value_by_currency": [{"currency": "TRY", "amount": 400}],
           "api_key": "SECRET", "customer": {"email": "person@example.test"}}
    _add(state, "valid", "stock.inventory_overview", raw)
    _add(state, "failed", "finance.cashflow_summary", raw)
    state.completed_steps[-1].status = "failed"
    _add(state, "unverified", "finance.cashflow_summary", raw)
    state.completed_steps[-1].verification_status = "pending"
    _add(state, "prepare", "reports.xlsx.prepare", raw)
    context = _calculation_goal_context(state, [])
    assert [row["source_step_id"] for row in context["completed_read_observations"]] == ["valid"]
    assert "SECRET" not in json.dumps(context) and "person@example.test" not in json.dumps(context)
    before = context["completed_read_observations"][0]["source_result_hash"]
    raw["stock_value_by_currency"][0]["amount"] = 600
    assert _calculation_goal_context(state, [])["completed_read_observations"][0]["source_result_hash"] != before


def test_canonical_item_sales_period_bounds_survive_arithmetic_and_prove_adjacent_periods():
    from AI.processors.semantic_verifier import _calculation_period_relation_problems
    state = AgentSessionState(goal="Compare equal adjacent sales periods", active_domain="general")
    sources = []
    for identity, start, end, amount in (("prior", 1790542800000, 1791147599999, 800),
                                        ("current", 1791147600000, 1791752399999, 3000)):
        result = {"period": "last_7_days", "start_date_ms": start, "end_date_ms": end,
                  "total_gross_amount": amount, "currency": "TRY"}
        _add(state, identity, "orders.item_sales_summary", result)
        sources.append({"source_id": identity, "source_step_id": identity,
                        "operation_id": "orders.item_sales_summary", "result": result})
    calculation = calculate_observations(sources=sources, calculations=[{"calculation_id": "difference",
        "operator": "subtract", "operands": [{"source_id": "current", "path": "total_gross_amount"},
                                               {"source_id": "prior", "path": "total_gross_amount"}]}])
    assert calculation.success, calculation.message
    _add(state, "difference", "analysis.calculate", calculation.data)
    verified = verified_observation_calculations(state)
    assert len(verified) == 1 and verified[0]["result"] == "2200.00"
    periods = {row["source_step_id"]: row["period"] for row in verified[0]["source_receipts"]}
    assert periods["prior"]["start_date_ms"] == 1790542800000
    verdict = {"period_relations": [{"relation": "previous_equal_period", "left_source_step_id": "current",
                                     "right_source_step_id": "prior"}]}
    observations = []
    assert _calculation_period_relation_problems(verdict, verified, observed_relations=observations) == []
    assert observations[0]["prior_source_step_id"] == "prior"
    assert observations[0]["current_source_step_id"] == "current"


@pytest.mark.parametrize("period", [
    {"start_date_ms": 10}, {"end_date_ms": 20},
    {"start_date_ms": True, "end_date_ms": 20},
    {"start_date_ms": 10, "end_date_ms": float("nan")},
    {"start_date_ms": 20, "end_date_ms": 10},
    {"start_ms": 10, "end_ms": 20, "start_date_ms": 11, "end_date_ms": 20},
    {"start_ms": 10, "end_ms": 20, "start_date": "2026-10-01", "end_date": "2026-10-07"},
    {"start_ms": 10, "end_ms": 20, "start_date": "2026-10-01"},
])
def test_missing_invalid_or_conflicting_numeric_period_bounds_fail_closed(period):
    from AI.processors.semantic_verifier import _observed_period_bounds
    assert _observed_period_bounds(period) is None


def test_matching_numeric_and_explicit_utc_calendar_bounds_agree_with_inclusive_last_millisecond():
    from datetime import datetime, timezone
    from AI.processors.semantic_verifier import _observed_period_bounds
    start = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp() * 1000) - 1
    assert _observed_period_bounds({"start_date_ms": start, "end_date_ms": end,
        "start_date": "2026-10-01", "end_date": "2026-10-07"}) == (start, end)
