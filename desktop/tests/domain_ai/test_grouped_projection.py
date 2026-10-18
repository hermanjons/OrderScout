import json

import pytest

from AI.processors import task_runtime, response_verifier, semantic_contracts
from AI.processors.grouped_projection import normalize_grouped_projection
from AI.processors.session_state import AgentSessionState, AgentTaskStep


def interpreted(message, limit=7):
    payload = {
        "mode": "inspect", "domain": "orders", "objective": message,
        "intent_kind": "data_read", "request_shape": "record_list",
        "entity": "order", "metric": "summary", "status_scope": "all",
        "record_scope": "all_matching", "period": "all", "freshness": "local_snapshot",
        "information_source": "local_business_data", "operation_policy": "allow_new_operations",
        "requires_clarification": False, "missing_input": "none", "population_basis": "entity_records",
        "requested_fields": ["item_sales_rows"],
        "grouped_projection": {"group_by": "product", "fields": ["product_name", "quantity", "order_count"], "limit": limit},
    }
    result = task_runtime.interpret_agent_turn(message, planner_client=lambda _: json.dumps(payload))
    assert result.success, result.message
    return result.data


@pytest.mark.parametrize("message", [
    "İlk yedi ürün hangileri? Her biri için satılan adet ve yer aldığı sipariş sayısını göster.",
    "Show seven products with units sold and distinct order counts per product.",
])
def test_group_columns_do_not_become_population_or_order_detail_metrics(message):
    turn = interpreted(message)
    contract = turn["semantic_contract"]
    assert turn["requested_fields"] == ["item_sales_rows"]
    assert contract["metric_requirements"] == ["orders.item_sales_summary"]
    assert contract["grouped_projection"]["limit"] == 7
    calls = []
    def planner(prompt):
        calls.append(prompt)
        return json.dumps({"steps": [{"id": "model_groups", "operation_id": "orders.item_sales_summary",
            "arguments": {"group_by": "product", "limit": 7, "period": "all"}, "depends_on": []}]})
    ids, meta = task_runtime._orders_task_plan(message, planner_client=planner, turn_interpretation=turn, max_steps=4)
    assert ids == ["model_groups"], meta
    assert len(calls) == 1
    assert meta["source"] == "llm_direct"
    assert not meta["deterministic_business_steps_inserted"]
    assert semantic_contracts.validate_orders_read_arguments(contract, "orders.item_sales_summary", {"limit": 5})


def test_grouped_response_checks_requested_columns_and_preserves_seven_rows():
    message = "Ürünleri satılan adet ve sipariş sayısıyla göster."
    turn = interpreted(message)
    rows = [{"product_name": f"Product {chr(65+i)}", "quantity": 21+i, "order_count": 3+i,
             "gross_amount": 1000+i, "currency": "TRY", "rank": i+1} for i in range(7)]
    state = AgentSessionState(goal=message, active_domain="orders", status="complete")
    state.active_entities["turn_interpretation"] = turn
    state.completed_steps = [AgentTaskStep(index=1, prompt=message, status="completed", verification_status="observed",
        tool_names=["orders.item_sales_summary"], result_data={"tool_result": {"rows": rows, "group_by": "product", "period": "all"}})]
    answer = "| Ürün | Satılan adet | Sipariş sayısı |\n| --- | --- | --- |\n" + "\n".join(
        f"| {r['product_name']} | {r['quantity']} | {r['order_count']} |" for r in rows)
    result = response_verifier.verify_response_projection(answer, state, source="test")
    assert result.success, result.data
    swapped = answer.replace("| 21 | 3 |", "| 3 | 21 |")
    assert not response_verifier.verify_response_projection(swapped, state, source="test").success
    fallback = response_verifier.project_fallback_response(state, "")
    assert "Product G" in fallback
    assert "brut" not in fallback and "1000" not in fallback
    checked = response_verifier.verify_response_projection(fallback, state, source="test")
    assert checked.success, checked.data
    evidence = response_verifier.response_evidence_projection(state)
    assert len(evidence["grouped_rows"]) == 7
    assert all(set(r) == {"product_name", "quantity", "order_count"} for r in evidence["grouped_rows"])
    extra = answer.replace("| Product A |", "| Product A brut: 1000 |")
    assert not response_verifier.verify_response_projection(extra, state, source="test").success
    result_data = state.completed_steps[0].result_data["tool_result"]
    result_data["product_count"] = 7
    result_data["rows"] = rows[:6]
    incomplete = response_verifier.verify_response_projection(answer, state, source="test")
    assert not incomplete.success
    assert "grouped_rows_incomplete" in incomplete.data["response_verification"]["reason_codes"]
    final = task_runtime._finalize_task_answer(state)
    assert state.status == "failed"
    assert "Product A" not in final
    assert state.active_entities["response_synthesis"]["unverified_answer_suppressed"] is True


def test_grouped_decimal_amounts_in_authoritative_fallback_are_verified():
    rows = [
        {
            "product_name": f"Product {index}",
            "quantity": 10 + index,
            "order_count": 5 + index,
            "gross_amount": amount,
            "currency": "TRY",
        }
        for index, amount in enumerate((447983.29, 97100.0, 492.0, 2100.0, 1662.5), 1)
    ]
    state = AgentSessionState(goal="En çok satan ilk 5 ürün hangileri?", active_domain="orders", status="complete")
    state.active_entities["turn_interpretation"] = {
        "requested_fields": ["item_sales_rows", "currency"],
        "semantic_contract": {
            "grouped_projection": {
                "group_by": "product",
                "fields": ["product_name", "quantity", "order_count", "gross_amount", "currency"],
                "limit": 5,
            },
        },
    }
    state.completed_steps = [AgentTaskStep(
        index=1,
        prompt=state.goal,
        status="completed",
        verification_status="observed",
        tool_names=["orders.item_sales_summary"],
        result_data={"tool_result": {
            "rows": rows,
            "product_count": 5,
            "currency": "TRY",
            "group_by": "product",
            "period": "all",
        }},
    )]

    fallback = response_verifier.project_fallback_response(state, "")
    assert response_verifier.verify_response_projection(fallback, state, source="test").success
    changed = fallback.replace("447.983,29", "447.983,28")
    assert not response_verifier.verify_response_projection(changed, state, source="test").success


def test_invalid_grouped_columns_fail_instead_of_silently_changing_grain():
    for fields in (["product_name", "customer_name"], ["quantity"], ["product_name", "count"]):
        with pytest.raises(ValueError):
            normalize_grouped_projection({"group_by": "product", "fields": fields, "limit": 7})


def test_general_assessment_with_null_grouping_keeps_broad_analysis():
    payload = {
        "objective": "Mağazamdaki siparişleri genel olarak değerlendir",
        "mode": "inspect", "domain": "orders", "intent_kind": "data_read",
        "request_shape": "broad_analysis", "entity": "order", "metric": "summary",
        "requested_fields": ["count", "status", "amount", "currency", "item_sales_rows"],
        "grouped_projection": None, "requires_clarification": False,
        "information_source": "local_business_data", "population_basis": "entity_records",
    }
    result = task_runtime.interpret_agent_turn(
        "Mağazamdaki siparişleri genel olarak değerlendir.",
        planner_client=lambda _: json.dumps(payload),
    )
    assert result.success, result.message
    contract = result.data["semantic_contract"]
    assert contract["request_shape"] == "broad_analysis"
    assert not contract.get("grouped_projection")
