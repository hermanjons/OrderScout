from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from AI.processors import response_verifier, task_runtime
from AI.processors.session_state import AgentSessionState
from Orders.processors.agentic_metrics import ORDER_ITEM_SALES_REPORT_METRIC


def captured_state():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "business_glm_broad_summary_evidence.json").read_text(encoding="utf-8"))
    assert fixture["provenance"]["original_final_texts_retained"] is False
    state = AgentSessionState.from_dict(deepcopy(fixture["state_evidence"]))
    # The real campaign failed at final projection. This regression supplies a
    # new, constructed answer after its actual source reads; it cannot upgrade
    # the historical campaign or recreate missing original model text.
    state.status = "complete"
    return state


def constructed_candidate(state):
    answer = response_verifier.project_fallback_response(state, "")
    cross = task_runtime._cross_business_safe_summary(response_verifier.response_evidence_projection(state))
    return "\n\n".join(part for part in (answer, cross) if part)


def reasons(result):
    return result.data["response_verification"]["reason_codes"]


def test_actual_general_broad_contract_projects_aggregate_and_all_current_read_domains():
    state = captured_state()
    assert "business_read_domains" not in state.active_entities
    projection = response_verifier.response_evidence_projection(state)
    cross = projection["cross_business_read"]
    assert cross["requested_domains"] == []
    assert cross["observed_domains"] == ["finance", "orders", "stock"]
    assert cross["projection_basis"] == "current_task_observations"
    assert [(r["period_label"], r["total_orders"], r["estimated_revenue"])
            for r in cross["orders"]["summaries"]] == [
        ("2026-10-05..2026-10-11", 3, 3000.0), ("2026-09-28..2026-10-04", 2, 800.0),
    ]
    assert cross["stock"]["stock_value_by_currency"] == [
        {"currency": "TRY", "amount": 400.0}, {"currency": "USD", "amount": 30.0},
    ]
    assert [(r["currency"], r["combined_net"]) for r in cross["finance"]["currency_totals"]] == [
        ("TRY", 200.0), ("USD", 20.0),
    ]
    answer = constructed_candidate(state)
    assert "Pilot Kupa:" not in answer and "Pilot Filtre:" not in answer
    result = response_verifier.verify_response_projection(answer, state, source="constructed_regression_candidate")
    assert result.success, result.data


@pytest.mark.parametrize("explicit_shape", ["record_list", "list", "detail", "report_requirement", "direct_rows", "grouped_rows"])
def test_explicit_product_record_contract_cannot_be_satisfied_by_an_aggregate_summary(explicit_shape):
    state = captured_state()
    answer = constructed_candidate(state)
    interpretation = state.active_entities["turn_interpretation"]
    contract = interpretation["semantic_contract"]
    if explicit_shape == "record_list":
        interpretation["request_shape"] = contract["request_shape"] = "record_list"
    elif explicit_shape in {"list", "detail"}:
        contract["metric"] = explicit_shape
    elif explicit_shape == "report_requirement":
        contract["metric_requirements"] = [ORDER_ITEM_SALES_REPORT_METRIC]
    elif explicit_shape == "direct_rows":
        interpretation["direct_output_fields"] = ["item_sales_rows"]
    else:
        contract["grouped_projection"] = {"group_by": "product", "fields": ["product_name", "quantity"], "limit": 5}
    assert not response_verifier._general_broad_summary_requested(state)
    if explicit_shape != "record_list":
        assert response_verifier.response_evidence_projection(state)["cross_business_read"]["observed_domains"] == ["finance", "orders", "stock"]
    result = response_verifier.verify_response_projection(answer, state, source="constructed_missing_record_candidate")
    assert not result.success, result.data
    assert any("item_sales" in code or "grouped" in code for code in reasons(result)), result.data


@pytest.mark.parametrize("missing_domain", ["stock", "finance"])
def test_uncompleted_unverified_or_mismatched_receipt_is_not_a_current_cross_domain_observation(missing_domain):
    original = captured_state()
    for invalidity in ["failed", "unverified", "wrong_owner", "wrong_producer"]:
        state = deepcopy(original)
        step = next(st for st in state.completed_steps if st.operation_domain == missing_domain)
        if invalidity == "failed":
            step.status = "failed"
        elif invalidity == "unverified":
            step.verification_status = "pending"
        elif invalidity == "wrong_owner":
            step.operation_domain = "general"
        else:
            step.result_data["tool_result"]["tool"] = "artifacts.read"
        cross = response_verifier.response_evidence_projection(state)["cross_business_read"]
        assert missing_domain not in cross["observed_domains"]
        assert missing_domain not in cross


def test_stock_amounts_keep_native_currencies_and_cannot_disappear_from_general_summary():
    state = captured_state()
    answer = constructed_candidate(state)
    wrong_currency = answer.replace("30.00 USD", "30.00 TRY")
    assert wrong_currency != answer
    result = response_verifier.verify_response_projection(wrong_currency, state, source="constructed_wrong_currency_candidate")
    assert not result.success
    assert "cross_stock_value_currency_pair_missing" in reasons(result)
    result = response_verifier.verify_response_projection(answer.split("Stokta")[0], state, source="constructed_omitted_stock_candidate")
    assert not result.success
    assert any(code.startswith("cross_stock_") for code in reasons(result)), result.data


def test_real_finalization_accepts_constructed_grounded_summary_through_observed_final_text_client():
    from AI.processors.business_agent_acceptance_cli import ObservedCloudClient
    state = captured_state()
    candidate = constructed_candidate(state)
    rows = []

    class Client:
        model_name = "regression/model"
        resource_plan = {"requested_model": "regression/model", "actual_model": "regression/model"}
        def invoke_final_text(self, prompt):
            assert "cross_business_read" in prompt
            return candidate
        def invoke_json_text(self, prompt, schema):
            assert "business assessment verifier" in prompt
            assert '"stock_value_by_currency"' in prompt
            assert '"source_snapshot_hash"' in prompt
            assert schema["required"] == ["supported", "reason_codes", "findings"]
            return json.dumps({"supported": True, "reason_codes": [], "findings": []})

    observed = ObservedCloudClient(Client(), rows.append)
    answer = task_runtime._finalize_task_answer(state, chat_client=observed)
    assert state.active_entities["response_synthesis"]["candidate_accepted"], state.active_entities["response_synthesis"]
    assert candidate in answer
    final_rows = [row for row in rows if row["method"] == "invoke_final_text"]
    assert len(final_rows) == 1
    assert final_rows[0]["response"] == candidate
    assert any(row["method"] == "invoke_json_text" for row in rows)
