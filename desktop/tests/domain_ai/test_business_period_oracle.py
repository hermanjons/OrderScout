"""Independent fixture oracle accepts complete canonical item sales receipts.

Actual Orders/Stock/Finance tools read the isolated SQLite fixture. Corruption
cases modify those genuine read receipts solely to test rejection boundaries.
"""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from AI.processors import tools
from AI.processors.business_acceptance_evidence import validate_fixture_observations
from AI.processors.business_acceptance_fixtures import seed_business_fixture


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    root = tmp_path_factory.mktemp("canonical-period-oracle")
    database = root / "business.sqlite3"
    fixture = seed_business_fixture(str(database), isolation_root=root)
    anchor = datetime.fromisoformat(fixture["as_of"]).date()
    results = []
    for start, end in ((anchor - timedelta(days=6), anchor), (anchor - timedelta(days=13), anchor - timedelta(days=7))):
        result = tools.orders_item_sales_summary(db_name=str(database), period="custom",
            start_date=start.isoformat(), end_date=end.isoformat(), api_account_ids=[101], group_by="product", limit=100)
        assert result.success, result.message
        results.append(result.data)
    for result in (tools.stock_inventory_overview(db_name=str(database)),
                   tools.finance_cashflow_summary(db_name=str(database), period="this_month")):
        assert result.success, result.message
        results.append(result.data)
    steps = [{"step_id": "read_" + str(index), "status": "completed", "verification_status": "observed",
              "tool_names": [result["tool"]], "result_data": {"tool_result": result}}
             for index, result in enumerate(results)]
    return fixture, {"raw_turn_data": {"state": {"completed_steps": steps}}}


def previous_result(turn):
    return turn["raw_turn_data"]["state"]["completed_steps"][1]["result_data"]["tool_result"]


def test_actual_canonical_item_sales_reads_prove_both_fixture_periods_without_summary_calls(observed):
    fixture, turn = observed
    evidence = validate_fixture_observations(turn, fixture)
    assert evidence["passed"], evidence
    assert all(evidence["checks"].values())
    for period in ("recent", "previous"):
        assert {row["operation_id"] for row in evidence["proof"][period]["count_receipts"]} == {"orders.item_sales_summary"}
        assert {row["operation_id"] for row in evidence["proof"][period]["revenue_receipts"]} == {"orders.item_sales_summary"}
    prior = previous_result(turn)
    assert prior["order_count"] == prior["matched_order_count"] == prior["population_order_count"] == 2
    assert prior["total_gross_amount"] == fixture["orders"]["previous_revenue_try"] == 800


def test_exact_complete_ms_aliases_are_accepted_and_do_not_change_original_canonical_receipt(observed):
    fixture, original = observed
    for remove_canonical in (False, True):
        turn = deepcopy(original)
        for step in turn["raw_turn_data"]["state"]["completed_steps"][:2]:
            result = step["result_data"]["tool_result"]
            result["start_ms"], result["end_ms"] = result["start_date_ms"], result["end_date_ms"]
            if remove_canonical:
                result.pop("start_date_ms")
                result.pop("end_date_ms")
        assert validate_fixture_observations(turn, fixture)["passed"]
    assert "start_ms" not in previous_result(original)


@pytest.mark.parametrize("corruption", ["wrong_dates", "incomplete_canonical", "no_bounds", "conflicting_alias",
    "incomplete_alias", "boolean_dates", "missing_hash", "malformed_hash", "other_account", "other_environment",
    "duplicate_scope", "not_complete", "truncated", "identity_filter", "boolean_filter", "partial_matched",
    "partial_population", "boolean_count", "wrong_count", "failed_step", "unobserved_step"])
def test_wrong_or_partial_item_population_cannot_prove_previous_period(observed, corruption):
    fixture, original = observed
    turn = deepcopy(original)
    result = previous_result(turn)
    if corruption == "wrong_dates":
        result["end_date_ms"] += 86400000
    elif corruption == "incomplete_canonical":
        result.pop("end_date_ms")
    elif corruption == "no_bounds":
        result.pop("start_date_ms"); result.pop("end_date_ms")
    elif corruption == "conflicting_alias":
        result["start_ms"] = result["start_date_ms"]
        result["end_ms"] = result["end_date_ms"] + 1
    elif corruption == "incomplete_alias":
        result["start_ms"] = result["start_date_ms"]
    elif corruption == "boolean_dates":
        result["start_date_ms"] = True
    elif corruption == "missing_hash":
        result.pop("source_snapshot_hash")
    elif corruption == "malformed_hash":
        result["source_snapshot_hash"] = "not-a-source-hash"
    elif corruption == "other_account":
        result["requested_api_account_ids"] = [102]
    elif corruption == "other_environment":
        result["account_scopes"][0]["environment"] = "production"
    elif corruption == "duplicate_scope":
        result["account_scopes"].append(deepcopy(result["account_scopes"][0]))
    elif corruption == "not_complete":
        result["metrics_complete"] = False
    elif corruption == "truncated":
        result["truncated"] = True
    elif corruption == "identity_filter":
        result["identity_filter_count"] = 1
    elif corruption == "boolean_filter":
        result["identity_filter_count"] = False
    elif corruption == "partial_matched":
        result["matched_order_count"] = 1
    elif corruption == "partial_population":
        result["population_order_count"] = 3
    elif corruption == "boolean_count":
        result["order_count"] = True
    elif corruption == "wrong_count":
        result.update(order_count=1, matched_order_count=1, population_order_count=1)
    elif corruption == "failed_step":
        turn["raw_turn_data"]["state"]["completed_steps"][1]["status"] = "failed"
    else:
        turn["raw_turn_data"]["state"]["completed_steps"][1]["verification_status"] = "failed"
    evidence = validate_fixture_observations(turn, fixture)
    assert not evidence["checks"]["orders_previous_count"]
    # A consistent but incorrect count does not alter independent gross facts.
    if corruption != "wrong_count":
        assert not evidence["checks"]["orders_previous_revenue_try"]
    assert evidence["checks"]["orders_recent_count"] and evidence["checks"]["stock_separate_currency_values"]


@pytest.mark.parametrize("corruption", ["extra_currency", "row_currency", "wrong_gross", "missing_currency",
    "map_mismatch", "boolean_amount", "string_amount", "duplicate_rows", "missing_rows", "row_total_mismatch"])
def test_item_gross_requires_exact_numeric_try_complete_rows_without_extra_or_duplicate_currencies(observed, corruption):
    fixture, original = observed
    turn = deepcopy(original)
    result = previous_result(turn)
    if corruption == "extra_currency":
        result["gross_amount_by_currency"]["USD"] = 800
    elif corruption == "row_currency":
        result["rows"][0]["currency"] = "USD"
    elif corruption == "wrong_gross":
        result["total_gross_amount"] = 999
    elif corruption == "missing_currency":
        result.pop("currency")
    elif corruption == "map_mismatch":
        result["gross_amount_by_currency"]["TRY"] = 999
    elif corruption == "boolean_amount":
        result["total_gross_amount"] = True
    elif corruption == "string_amount":
        result["total_gross_amount"] = "800"
    elif corruption == "duplicate_rows":
        duplicate = deepcopy(result["rows"][0])
        result["rows"][0]["gross_amount"] = duplicate["gross_amount"] = 400
        result["rows"].append(duplicate)
    elif corruption == "missing_rows":
        result["rows"] = []
    else:
        result["rows"][0]["gross_amount"] = 999
    evidence = validate_fixture_observations(turn, fixture)
    assert evidence["checks"]["orders_previous_count"]
    assert not evidence["checks"]["orders_previous_revenue_try"]
