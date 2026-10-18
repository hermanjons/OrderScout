import json
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from AI.processors import task_runtime, tools, response_verifier
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from Orders.processors import agentic_repository as repo
from Feedback.processors.pipeline import Result


@pytest.mark.parametrize("message", [
    "Riskli siparişlerin sayısı ve durum dağılımı neden böyle; gerçekten gecikmişler mi?",
    "Explain the risk count, status distribution and measurement limits.",
    "Bu risklerin hangi durumlarda olduğunu ve gerekçesini açıkla.",
])
def test_risk_population_does_not_require_overall_order_metrics(message):
    payload = {"mode": "inspect", "domain": "orders", "objective": message,
        "intent_kind": "data_read", "request_shape": "focused_analysis",
        "entity": "order", "metric": "summary", "requested_fields": ["risk"],
        "status_scope": "all", "period": "all", "record_scope": "all_matching",
        "information_source": "local_business_data", "requires_clarification": False}
    result = task_runtime.interpret_agent_turn(message, planner_client=lambda _: json.dumps(payload))
    assert result.success, result.message
    turn = result.data
    assert turn["requested_fields"] == ["risk"]
    assert turn["semantic_contract"]["metric_requirements"] == [task_runtime.ORDER_FULFILLMENT_RISK_COUNT_METRIC]
    state = AgentSessionState(goal=message, active_domain="orders", status="complete")
    state.active_entities["turn_interpretation"] = turn
    state.completed_steps = [AgentTaskStep(index=1, prompt="read risk", status="completed",
        tool_names=["orders.fulfillment_risk_count"], result_data={"tool_result": {
            "count": 3, "risk_count": 3, "risk_evidence": {
                "status_counts": {"Picking": 2, "ReadyToShip": 1},
                "delay_assessment": "not_measured_by_this_operation"}}})]
    answer = "Fulfillment riski: 3. Picking: 2, ReadyToShip: 1."
    checked = response_verifier.verify_response_projection(answer, state, source="test")
    assert checked.success, checked.data
    assert not response_verifier.verify_response_projection(
        answer.replace("riski: 3", "riski: 9"), state, source="test").success


def test_explicit_composite_model_projection_keeps_overall_metrics():
    payload = {"mode": "inspect", "domain": "orders", "objective": "Compare overall orders and risk",
        "intent_kind": "data_read", "request_shape": "focused_analysis",
        "entity": "order", "metric": "summary", "requested_fields": ["count", "status", "risk"],
        "requires_clarification": False}
    result = task_runtime.interpret_agent_turn("Tüm siparişlerin sayısı, durumları ve riskleri", planner_client=lambda _: json.dumps(payload))
    assert result.success, result.message
    assert {"count", "status", "risk"} <= set(result.data["requested_fields"])
    assert task_runtime.ORDER_TOTAL_COUNT_METRIC in result.data["semantic_contract"]["metric_requirements"]
    assert task_runtime.ORDER_STATUS_DISTRIBUTION_METRIC in result.data["semantic_contract"]["metric_requirements"]


@pytest.mark.parametrize("population,fields,expected", [
    ("fulfillment_risks", ["count", "status", "reason"], ["risk"]),
    ("fulfillment_risks", ["risk", "count", "status", "scope"], ["risk", "scope"]),
    ("all_orders", ["count", "status", "risk"], ["count", "status", "risk"]),
])
def test_model_population_owns_aggregate_columns(population, fields, expected):
    payload = {"mode": "inspect", "domain": "orders", "objective": "Explain these counts and statuses",
        "intent_kind": "data_read", "request_shape": "focused_analysis", "entity": "order",
        "metric": "summary", "requested_fields": fields, "metric_population": population,
        "requires_clarification": False}
    result = task_runtime.interpret_agent_turn("Bu sayıların durum dağılımını açıkla", planner_client=lambda _: json.dumps(payload))
    assert result.success, result.message
    assert result.data["requested_fields"] == expected
    if population == "fulfillment_risks":
        assert result.data["semantic_contract"]["metric_population"] == population
        assert result.data["semantic_contract"]["metric_requirements"] == [task_runtime.ORDER_FULFILLMENT_RISK_COUNT_METRIC]


def test_population_cannot_silently_discard_record_projection():
    with pytest.raises(ValueError, match="risk_population_projection_conflict"):
        task_runtime._model_risk_summary_fields({"metric_population": "fulfillment_risks",
            "requested_fields": ["risk", "order_number"]})


def test_risk_definition_and_distribution_cover_full_population_before_limit():
    def order(status, tracking="", provider="", date=1):
        return SimpleNamespace(status=status, shipmentPackageStatus=status, cargoTrackingNumber=tracking,
            cargoProviderName=provider, orderDate=date, orderNumber="private-id", api_account_id=1)
    rows = [order("Picking"), order("ReadyToShip", "tracking", "carrier"),
            order("Shipped", "", "carrier"), order("Delivered")]
    with patch.object(repo, "get_latest_orders_filtered", return_value=Result.ok("read", data={"orders": rows})):
        result = repo.analyze_fulfillment_risks(now_ms=100*3600000, limit=1)
    assert result.success, result.message
    data = result.data
    assert data["risk_count"] == 3 and data["listed_count"] == 1 and data["truncated"]
    evidence = data["risk_evidence"]
    assert evidence["status_counts"] == {"Picking": 1, "ReadyToShip": 1, "Shipped": 1}
    assert evidence["reason_counts"] == {"tracking_missing": 2, "cargo_provider_missing": 1, "order_age_over_threshold_while_ready": 2}
    assert evidence["delay_assessment"] == "not_measured_by_this_operation"
    assert evidence["age_measurement"]["origin_field"] == "orderDate"
    assert evidence["age_measurement"]["time_in_status_measured"] is False
    assert "private-id" not in json.dumps(evidence)
    with patch.object(tools, "fulfillment_risk_summary", return_value=result):
        counted = tools.orders_fulfillment_risk_count(period="all")
    assert counted.data["risk_evidence"] == evidence
    state = AgentSessionState(goal="Explain risk", active_domain="orders", status="complete")
    state.active_entities["turn_interpretation"] = {"requested_fields": ["risk"], "semantic_contract": {"projection": ["risk"]}}
    state.completed_steps = [AgentTaskStep(index=1, prompt="Read risks", status="completed", tool_names=["orders.fulfillment_risk_count"], result_data={"tool_result": counted.data})]
    projected = response_verifier.response_evidence_projection(state)
    assert projected["risk_evidence"] == evidence
    assert "private-id" not in json.dumps(projected)
    answer = "Fulfillment riski: 3. order_age_over_threshold_while_ready."
    assert response_verifier.verify_response_projection(answer, state, source="test").success
    invented = answer + " ORDER_NOT_OBSERVED_99999"
    counted.data["unrelated_text"] = "ORDER_NOT_OBSERVED_99999"
    assert not response_verifier.verify_response_projection(invented, state, source="test").success


def test_formula_less_calculation_is_reinterpreted_not_executed():
    bad = {"mode": "inspect", "domain": "orders", "objective": "Explain the risk metric",
        "intent_kind": "data_read", "request_shape": "focused_analysis", "metric": "summary",
        "entity": "order", "requested_fields": ["risk", "calculation"], "requires_clarification": False}
    good = dict(bad, requested_fields=["risk"])
    calls = []
    def planner(prompt):
        calls.append(prompt)
        return json.dumps(bad if len(calls) == 1 else good)
    result = task_runtime.interpret_agent_turn("Risk tanımı nedir?", planner_client=planner)
    assert result.success, result.message
    assert len(calls) == 2 and "calculation_projection_without_formula" in calls[1]
    assert "calculation" not in result.data["requested_fields"]


def test_policy_label_cannot_discard_model_requested_business_evidence():
    bad = {"mode": "explain", "domain": "orders", "objective": "Explain the observed risks",
        "intent_kind": "policy_explanation", "request_shape": "policy_explanation",
        "explanation_topics": ["data_source"], "requested_fields": ["risk"], "requires_clarification": False}
    good = dict(bad, mode="inspect", intent_kind="data_read", request_shape="focused_analysis",
        entity="order", metric="summary", explanation_topics=[])
    calls = []
    def planner(prompt):
        calls.append(prompt)
        return json.dumps(bad if len(calls) == 1 else good)
    result = task_runtime.interpret_agent_turn("Riskli kayıtların nedenini açıkla", planner_client=planner)
    assert result.success, result.message
    assert any("policy_business_projection_conflict" in prompt for prompt in calls[1:]), result.data.get("turn_interpretation_repair")
    assert result.data["intent_kind"] == "data_read"
    assert "risk" in result.data["requested_fields"]


def test_rejected_model_decisions_cannot_become_canonical_business_plans():
    calls = []
    def planner(prompt):
        calls.append(prompt)
        return "invalid model output"
    with patch.object(task_runtime, "_safe_canonical_orders_read_recovery") as read, patch.object(
        task_runtime, "_safe_canonical_orders_prepare_recovery"
    ) as prepare:
        result = task_runtime.interpret_agent_turn("Siparişlerimi say", planner_client=planner)
    assert not result.success and not result.data["valid"]
    assert len(calls) == 2
    read.assert_not_called()
    prepare.assert_not_called()
    assert result.data["decision_path"] == "typed_model_turn_interpretation_failed"
