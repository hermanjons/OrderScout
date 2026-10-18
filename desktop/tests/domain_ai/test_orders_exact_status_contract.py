from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch

from sqlmodel import Session

from AI.processors import response_verifier, semantic_contracts, task_runtime, tools
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from Core.utils.model_utils import get_engine
from Orders.models.trendyol.models import OrderData, OrderHeader, OrderItem
from Orders.processors import agentic_repository
from Orders.processors.agentic_metrics import ORDER_FILTERED_COUNT_METRIC, order_metric_operation_ids
from tests.support.db_case import IsolatedDbTestCase


MESSAGE = (
    "ReadyToShip görünen 48 siparişin tam listesini göster; sıra numarası, "
    "sipariş numarası, ürünler ve kargo firması yeterli. Müşteri bilgisi istemiyorum."
)


def interpretation():
    payload = {
        "mode": "inspect", "domain": "orders", "objective": MESSAGE,
        "intent_kind": "data_read", "request_shape": "record_list",
        "requested_fields": ["order_number", "item", "cargo"],
        "direct_output_fields": ["order_number", "item", "cargo"],
        "identifier_display": "ordinal", "entity": "order", "metric": "list",
        "status_scope": "ready_to_ship", "status_codes": ["ReadyToShip"],
        "record_scope": "all_matching", "period": "all",
        "freshness": "local_snapshot", "information_source": "local_business_data",
        "operation_policy": "allow_new_operations", "comparison_policy": "not_requested",
        "calculation_grouping": "none", "calculation_count": 0,
        "requires_clarification": False,
    }
    result = task_runtime.interpret_agent_turn(
        MESSAGE, planner_client=lambda _: json.dumps(payload)
    )
    assert result.success, result.message
    return result.data


def test_exact_status_and_identifier_projection_are_independent():
    interpreted = interpretation()
    contract = interpreted["semantic_contract"]
    assert contract["status_codes"] == ["ReadyToShip"]
    assert contract["status_scope"] == "all"
    assert interpreted["identifier_display"] == "ordinal"
    assert "order_number" in interpreted["requested_fields"]
    assert "order_number" in contract["projection"]
    assert task_runtime._canonical_recovered_orders_read_plan(interpreted, MESSAGE) is None
    assert semantic_contracts.expected_order_read_operations(contract) == {"orders.full_context"}
    assert semantic_contracts.validate_orders_read_arguments(
        contract, "orders.full_context", {"filters": {"statuses": ["ReadyToShip"]}}
    ) == ()
    for operation, arguments in (
        ("orders.ready_to_ship", {}),
        ("orders.full_context", {}),
        ("orders.full_context", {"filters": {"statuses": ["ReadyToShip", "Picking"]}}),
        ("orders.full_context", {"filters": {"status": "Picking"}}),
    ):
        assert semantic_contracts.validate_orders_read_arguments(contract, operation, arguments)
    # The boundary is generic: it preserves marketplace codes without a
    # ReadyToShip text matcher or a hardcoded marketplace status vocabulary.
    other = {**contract, "status_codes": ["MerchantPacking"]}
    assert semantic_contracts.validate_orders_read_arguments(
        other, "orders.full_context", {"filters": {"status": "MerchantPacking"}}
    ) == ()


def test_cancelled_reason_aggregate_uses_its_canonical_read_and_line_counts():
    message = "İptal nedenleri nelermiş?"
    contract = {
        "entity": "order",
        "metric": "list",
        "status_scope": "all",
        "status_codes": ["Cancelled"],
        "record_scope": "all_matching",
        "projection": ["reason"],
        "metric_requirements": ["orders.cancellation_reason_distribution"],
    }
    assert semantic_contracts.expected_order_read_operations(contract) == {"orders.cancellations"}
    assert semantic_contracts.validate_orders_read_arguments(
        contract, "orders.cancellations", {"period": "all"}
    ) == ()
    assert semantic_contracts.validate_orders_read_arguments(
        {**contract, "status_codes": ["Picking"]},
        "orders.cancellations",
        {"period": "all"},
    )
    constraints = semantic_contracts.business_read_plan_constraints(contract)
    assert constraints["operation_alternatives"] == ["orders.cancellations"]
    assert "exact_status_filter" not in constraints

    turn = {
        "valid": True,
        "mode": "inspect",
        "domain": "orders",
        "intent_kind": "data_read",
        "requested_fields": ["reason"],
        "semantic_contract": contract,
    }
    plan = {"steps": [{
        "id": "read_reasons",
        "operation_id": "orders.cancellations",
        "arguments": {"period": "all"},
        "depends_on": [],
        "expected_evidence": ["cancel_reasons"],
    }]}
    ids, metadata = task_runtime._orders_task_plan(
        message,
        planner_client=lambda _: json.dumps(plan),
        max_steps=3,
        turn_interpretation=turn,
    )
    assert ids == ["read_reasons"], metadata
    assert metadata["source"] == "llm_direct"
    assert not metadata.get("planner_repair_invoked")

    state = AgentSessionState(goal=message, active_domain="orders", status="complete")
    state.active_entities["turn_interpretation"] = turn
    state.completed_steps = [AgentTaskStep(
        index=1,
        prompt=message,
        status="completed",
        verification_status="observed",
        tool_names=["orders.cancellations"],
        result_data={"tool_result": {
            "tool": "orders.cancellations",
            "cancelled_orders": 3,
            "cancel_reasons": {"Stok tükendi": 4, "Hatalı fiyat": 1},
            "cancel_reason_count_unit": "order_line",
            "orders": [{"status": "Cancelled"}],
            "listed_count": 1,
            "truncated": True,
        }},
    )]
    answer = response_verifier.project_fallback_response(state, "")
    assert "sipariş kalemi sayısı" in answer
    assert response_verifier.verify_response_projection(answer, state, source="test").success
    wrong_unit = answer.replace("sipariş kalemi sayısı", "sipariş sayısı").replace(
        "Bir siparişte birden fazla kalem olabilir.", ""
    )
    checked = response_verifier.verify_response_projection(wrong_unit, state, source="test")
    assert not checked.success
    assert "cancellation_reason_count_unit_missing" in checked.data["response_verification"]["reason_codes"]


def test_exact_status_compiler_retains_model_graph_without_queue_rewrite():
    contract = interpretation()["semantic_contract"]
    specs = [{"id": "filtered_rows", "operation_id": "orders.full_context",
              "operation_domain": "orders", "depends_on": [],
              "arguments": {"filters": {"statuses": ["ReadyToShip"]}, "limit": 100}}]
    ids, compiled, metadata = task_runtime._compile_orders_direct_plan_specs(
        specs, MESSAGE, allowed_operations=tools.available_tools(), max_steps=8,
        semantic_contract=contract,
    )
    assert ids == ["filtered_rows"]
    assert compiled[0]["operation_id"] == "orders.full_context"
    assert compiled[0]["arguments"]["filters"] == {"statuses": ["ReadyToShip"]}
    assert metadata.get("semantic_missing_step_ids") == []


def test_exact_status_count_requires_filtered_query_not_named_business_queue():
    for status in ("ReadyToShip", "MerchantPacking"):
        message = f"Bu mağazadaki {status} siparişleri kaç tane?"
        payload = {
            "mode": "inspect", "domain": "orders", "objective": message,
            "intent_kind": "data_read", "request_shape": "scalar",
            "entity": "order", "metric": "count", "requested_fields": ["count"],
            "status_codes": [status], "status_scope": "ready_to_ship",
            "record_scope": "all_matching", "period": "all", "requires_clarification": False,
        }
        result = task_runtime.interpret_agent_turn(message, planner_client=lambda _: json.dumps(payload))
        assert result.success, result.message
        contract = result.data["semantic_contract"]
        assert contract["metric_requirements"] == [ORDER_FILTERED_COUNT_METRIC]
        assert set(order_metric_operation_ids(ORDER_FILTERED_COUNT_METRIC)) == {"orders.query"}
        assert semantic_contracts.expected_order_read_operations(contract) == {"orders.query"}
        plan = {"steps": [{"id": "filtered", "operation_id": "orders.query",
                           "arguments_json": json.dumps({"mode": "count", "filters": {"statuses": [status]}}),
                           "depends_on": [], "objective": message, "expected_evidence": ["count", "filters", "query_fingerprint"]}]}
        ids, meta = task_runtime._orders_task_plan(
            message, planner_client=lambda _: json.dumps(plan), max_steps=3, turn_interpretation=result.data
        )
        assert ids == ["filtered"], meta
        assert meta["source"] == "llm_direct", meta
        assert not meta.get("planner_repair_invoked"), meta


def test_model_sees_the_same_read_constraints_before_plan_and_repair():
    registry = tools.available_tools()
    for status in ("ReadyToShip", "MerchantPacking"):
        for metric, fields, expected in (
            ("list", ["item", "cargo", "order_number"], "orders.full_context"),
            ("count", ["count"], "orders.query"),
        ):
            contract = {
                "entity": "order", "metric": metric, "status_scope": "all",
                "status_codes": [status], "record_scope": "all_matching",
                "projection": fields,
            }
            expected_constraint = semantic_contracts.business_read_plan_constraints(contract)
            assert expected_constraint["operation_alternatives"] == [expected]
            assert expected_constraint["exact_status_filter"]["codes"] == [status]
            assert set(expected_constraint["operation_alternatives"]) == set(
                semantic_contracts.expected_order_read_operations(contract)
            )
            for compact in (False, True):
                initial = task_runtime._orders_plan_prompt(
                    "Read the requested population", 4, operation_candidates=registry,
                    semantic_contract=contract, compact_contract=compact,
                )
                repair = task_runtime._orders_plan_repair_prompt(
                    "Read the requested population", 4, operation_candidates=registry,
                    typed_context=[], semantic_contract=contract,
                    rejected_plan=[{"operation_id": "orders.ready_to_ship"}],
                    reason_codes=["exact_status_read_operation_mismatch"],
                    compile_evidence={"expected_typed_read_operations": [expected],
                                      "compiled_operation_ids": ["orders.ready_to_ship"]},
                    compact_contract=compact,
                )
                for prompt in (initial, repair):
                    line = next(x for x in prompt.splitlines() if x.startswith("ReadEvidenceContract="))
                    assert json.loads(line.split("=", 1)[1]) == expected_constraint
                assert '"expected_typed_read_operations"' in repair


def test_exact_list_repair_preserves_model_graph_and_exposes_required_capability():
    interpreted = interpretation()
    calls = []
    registry = tools.available_tools()

    def planner(prompt):
        calls.append(prompt)
        assert "- orders.full_context" in prompt
        assert "ReadEvidenceContract=" in prompt
        if len(calls) == 1:
            operation, arguments = "orders.ready_to_ship", {"limit": 48}
        else:
            assert '"expected_typed_read_operations": ["orders.full_context"]' in prompt
            operation, arguments = "orders.full_context", {
                "filters": {"statuses": ["ReadyToShip"]}, "limit": 100, "period": "all",
            }
        return json.dumps({"steps": [{"id": "model_read", "operation_id": operation,
                                     "arguments": arguments, "depends_on": []}]})

    # Even when keyword retrieval misses the necessary operation, evidence
    # constraints expose it to the model without constructing a replacement plan.
    with patch.object(task_runtime, "_planner_operation_candidates", return_value={
        "orders.ready_to_ship": registry["orders.ready_to_ship"],
    }):
        ids, metadata = task_runtime._orders_task_plan(
            MESSAGE, planner_client=planner, max_steps=4, turn_interpretation=interpreted,
        )
    assert len(calls) == 2
    assert ids == ["model_read"]
    assert metadata["source"] == "llm_direct_repaired"
    assert metadata["step_specs"][0]["operation_id"] == "orders.full_context"
    assert metadata["step_specs"][0]["arguments"] == {
        "filters": {"statuses": ["ReadyToShip"]}, "limit": 100, "period": "all",
    }
    assert metadata["deterministic_business_steps_inserted"] is False


def test_plan_repair_receives_field_failure_and_never_silently_drops_arguments():
    interpreted = interpretation()
    for repair_is_valid in (True, False):
        calls = []

        def planner(prompt):
            calls.append(prompt)
            arguments = {"filters": {"status": "ReadyToShip"}, "limit": 100, "period": "all"}
            if len(calls) == 1 or not repair_is_valid:
                arguments["mode"] = "list"
            if len(calls) == 2:
                assert '"reason_codes": ["arguments.mode:unknown"]' in prompt
                assert '"step_validation_errors"' in prompt
            return json.dumps({"steps": [{"id": "authored_read", "operation_id": "orders.full_context",
                                          "arguments": arguments, "depends_on": []}]})

        ids, metadata = task_runtime._orders_task_plan(
            MESSAGE, planner_client=planner, max_steps=4, turn_interpretation=interpreted,
        )
        assert len(calls) == 2
        diagnostic = metadata["initial_compile_verification"]["step_validation_errors"]
        assert diagnostic == [{"step_id": "authored_read", "operation_id": "orders.full_context",
                               "reason_codes": ["arguments.mode:unknown"]}]
        if repair_is_valid:
            assert ids == ["authored_read"]
            assert metadata["source"] == "llm_direct_repaired"
            assert metadata["step_specs"][0]["arguments"] == {
                "filters": {"status": "ReadyToShip"}, "limit": 100, "period": "all",
            }
            assert metadata["deterministic_business_steps_inserted"] is False
        else:
            assert ids == []
            assert metadata["source"] == "model_plan_rejected"
            assert metadata["repair_compile_verification"]["step_validation_errors"] == diagnostic


class TestExactStatusMaterialization(IsolatedDbTestCase):
    def seed(self):
        with Session(get_engine(self.db_path)) as session:
            for index in range(51):
                number = f"ORD-STATUS-{index + 1:03d}"
                status = "ReadyToShip" if index < 48 else "Picking"
                header = OrderHeader(orderNumber=number)
                session.add(header)
                session.flush()
                order = OrderData(
                    order_header_id=header.pk, orderNumber=number,
                    id=index + 1, shipmentPackageId=index + 1,
                    orderDate=1780000000000 + index, lastModifiedDate=1780000000100 + index,
                    status=status, shipmentPackageStatus=status, cargoProviderName="Aras",
                    customerFirstName="PrivateCustomer", totalPrice=100.0,
                )
                session.add(order)
                session.flush()
                session.add(OrderItem(
                    orderNumber=number, order_data_id=order.pk, lineId=index + 1,
                    productName=f"Ürün {index + 1}", quantity=1,
                    snapshotLastModifiedDate=1780000000200 + index,
                ))
            session.commit()

    def test_filtered_full_context_preserves_population_and_projection(self):
        self.seed()
        args = {"db_name": self.db_path, "filters": {"statuses": ["ReadyToShip"]}, "limit": 100}
        manual = agentic_repository.get_order_full_context(**args)
        ai = tools.orders_full_context(**args)
        assert manual.success and ai.success, (manual.message, ai.message)
        assert manual.data["order_numbers"] == ai.data["order_numbers"]
        assert ai.data["count"] == ai.data["total_count"] == 48
        assert ai.data["truncated"] is False
        result_fields = tools.available_tools()["orders.full_context"].result_schema["properties"]
        assert set(result_fields) <= set(ai.data)
        assert {"contexts", "order_numbers", "total_count", "truncated"} <= set(result_fields)
        assert {c["order"]["status"] for c in ai.data["contexts"]} == {"ReadyToShip"}
        assert all(c["items"] for c in ai.data["contexts"])
        exact = agentic_repository.get_order_full_context(
            db_name=self.db_path, order_numbers=manual.data["order_numbers"]
        )
        assert exact.success and exact.data["count"] == 48
        state = AgentSessionState(goal=MESSAGE, active_domain="orders", status="complete")
        state.active_entities["turn_interpretation"] = interpretation()
        state.completed_steps = [AgentTaskStep(
            index=1, prompt=MESSAGE, status="completed", tool_names=["orders.full_context"],
            result_data={"tool_result": ai.data},
        )]
        assert response_verifier._exact_status_read_evidence_problems(state) == []
        partial = deepcopy(state)
        partial.completed_steps[0].result_data["tool_result"]["contexts"].pop()
        assert "exact_status_full_list_incomplete" in response_verifier._exact_status_read_evidence_problems(partial)
        expanded = deepcopy(state)
        expanded.completed_steps[0].result_data["tool_result"]["contexts"][0]["order"]["status"] = "Picking"
        assert "exact_status_result_scope_mismatch" in response_verifier._exact_status_read_evidence_problems(expanded)

    def test_verified_failure_never_publishes_queue_count_as_list(self):
        state = AgentSessionState(goal=MESSAGE, active_domain="orders", status="complete")
        state.active_entities["turn_interpretation"] = interpretation()
        state.completed_steps = [AgentTaskStep(
            index=1, prompt=MESSAGE, status="completed", tool_names=["orders.ready_to_ship"],
            result_message="Kargoya hazır 286 sipariş var.",
            result_data={"tool_result": {"tool": "orders.ready_to_ship", "ready_to_ship": 286}},
        )]
        answer = task_runtime._finalize_task_answer(state, chat_client=None)
        assert "286" not in answer
        assert state.status == "failed"
        assert state.active_entities["response_synthesis"]["unverified_answer_suppressed"] is True
