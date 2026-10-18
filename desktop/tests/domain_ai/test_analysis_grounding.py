from __future__ import annotations

import json

import pytest

from AI.processors.analysis_grounding import assessment_context, assessment_scope_note, verify_assessment
from AI.processors.live_evidence import LiveEvidenceRedactor
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.processors.task_runtime import _finalize_task_answer


def analysis_state():
    state = AgentSessionState(goal="Siparişlerimin durumunu değerlendir", active_domain="orders", status="complete")
    state.active_entities["turn_interpretation"] = {
        "mode": "inspect", "intent_kind": "data_read", "request_shape": "broad_analysis",
        "requested_fields": ["count"],
        "semantic_contract": {"entity": "order", "metric": "count", "projection": ["count"]},
    }
    state.completed_steps = [AgentTaskStep(
        index=1, prompt="read", status="completed", verification_status="observed",
        tool_names=["orders.count"], result_message="570 sipariş var.",
        result_data={"answer": "570 sipariş var.", "tool_result": {
            "count": 570, "tool": "orders.count", "environment_by_account": {"1": "stage"},
        }},
    )]
    return state


def test_correct_count_cannot_make_unsupported_benchmark_an_accepted_answer():
    state = analysis_state()
    prompts = []

    def client(prompt):
        prompts.append(prompt)
        if prompt.startswith("OrderScout business assessment verifier"):
            bad = '"candidate": "570 sipariş var. Performansın ortalama."' in prompt
            return json.dumps({"supported": not bad, "reason_codes": ["unsupported_benchmark"] if bad else [],
                "findings": [{"claim": "Performansın ortalama.", "reason_code": "unsupported_benchmark"}] if bad else []})
        if prompt.startswith("Onceki final cevap"):
            assert '"claim": "Performansın ortalama."' in prompt
            assert "Full verified evidence and metric definitions:" in prompt
            return "570 sipariş var. Karşılaştırma olmadan performans derecesi belirleyemem."
        return "570 sipariş var. Performansın ortalama."

    answer = _finalize_task_answer(state, chat_client=client)
    synthesis = state.active_entities["response_synthesis"]
    assert synthesis["candidate_assessment"]["supported"] is False
    assert synthesis["repair_assessment"]["supported"] is True
    assert synthesis["repair_accepted"] is True
    assert "Performansın ortalama" not in answer
    assert "570" in answer and "Stage/test" in answer
    assert len([p for p in prompts if p.startswith("OrderScout business assessment verifier")]) == 2


def test_focused_risk_claim_requires_measurement_semantics_review():
    state = analysis_state()
    interpretation = state.active_entities["turn_interpretation"]
    interpretation.update(request_shape="focused_analysis", requested_fields=["risk"])
    result = state.completed_steps[0].result_data["tool_result"]
    result["risk_evidence"] = {"delay_assessment": "not_measured_by_this_operation"}
    prompts = []
    def client(prompt):
        prompts.append(prompt)
        return json.dumps({"supported": False, "reason_codes": ["unsupported_fact"],
            "findings": [{"claim": "bu kuyrukta 24 saattir bekliyor", "reason_code": "unsupported_fact"}]})
    checked = verify_assessment("286 sipariş bu kuyrukta 24 saattir bekliyor.", state,
        client=client, safe_projection={"risk_evidence": result["risk_evidence"]})
    assert checked["required"] and not checked["supported"]
    assert len(prompts) == 1 and "siparis tarihinden gecen sureyi" in prompts[0]
    span = checked["finding_spans"][0]
    assert "286 sipariş bu kuyrukta 24 saattir bekliyor."[span["start"]:span["end"]] == "bu kuyrukta 24 saattir bekliyor"
    assert "claim" not in checked and "bu kuyrukta" not in json.dumps(checked)


@pytest.mark.parametrize("findings", [[], [{"claim": "invented claim", "reason_code": "unsupported_fact"}],
    [{"claim": "570", "reason_code": "unsupported_cause"}], [{"claim": " ", "reason_code": "unsupported_fact"}]])
def test_unbound_or_missing_rejected_claim_cannot_be_trusted(findings):
    verdict = {"supported": False, "reason_codes": ["unsupported_fact"], "findings": findings}
    result = verify_assessment("570 sipariş var.", analysis_state(), client=lambda _: json.dumps(verdict), safe_projection={"count": 570})
    assert result["supported"] is False
    assert result["reason_codes"] == ["assessment_verifier_unavailable_or_invalid"]


@pytest.mark.parametrize("verdict", ["bad", '{}', '{"supported":true,"reason_codes":["unsupported_benchmark"]}', '{"supported":true,"reason_codes":["other"]}'])
def test_invalid_semantic_review_fails_closed(verdict):
    result = verify_assessment("570 sipariş var.", analysis_state(), client=lambda _: verdict, safe_projection={"count": 570})
    assert result["supported"] is False


def test_unobserved_or_failed_data_cannot_supply_stage_scope():
    state = analysis_state()
    assert assessment_scope_note(state)
    state.completed_steps[0].verification_status = "failed"
    assert assessment_context(state)["environments"] == []
    assert assessment_scope_note(state) == ""


def test_non_assessment_answer_does_not_invoke_semantic_review():
    state = analysis_state()
    state.active_entities["turn_interpretation"]["request_shape"] = "scalar"

    def forbidden(_):
        pytest.fail("A simple scalar is already verified by the numeric projection verifier")

    assert verify_assessment("570 sipariş var.", state, client=forbidden, safe_projection={})["supported"] is True


def test_repair_preserves_metric_definitions_and_rejects_feedback_for_another_candidate():
    import hashlib
    from AI.processors.task_runtime import _task_final_repair_prompt
    state = analysis_state()
    state.active_entities["turn_interpretation"]["requested_fields"] = ["risk"]
    step = state.completed_steps[0]
    step.tool_names = ["orders.fulfillment_risk_count"]
    step.result_data["tool_result"] = {"tool": "orders.fulfillment_risk_count", "risk_count": 286,
        "risk_evidence": {"age_measurement": {"origin": "orderDate", "time_in_status_measured": False},
            "delay_assessment": "not_measured_by_this_operation"}}
    candidate = "Mevcut durumda bekleme ölçüldü."
    prompt = _task_final_repair_prompt(state, rejected_candidate=candidate,
        reason_codes=["unsupported_fact"], authoritative_projection="286 risk var.",
        assessment_feedback={"candidate_sha256": hashlib.sha256(b'another candidate').hexdigest(),
            "finding_spans": [{"start": 0, "end": 5, "reason_code": "unsupported_fact"}]})
    assert "orderDate" in prompt and '"time_in_status_measured": false' in prompt
    assert "not_measured_by_this_operation" in prompt
    assert "Assessment findings: []" in prompt


def test_source_fingerprint_containing_phone_digits_remains_verifiable():
    digest = "05321234567" + "a" * 53
    payload = {
        "runtime_source_fingerprint": digest, "runtime_source_fingerprint_current": digest,
        "query_fingerprint": digest, "source_snapshot_hash": digest,
        "phone": "05321234567", "answer": "Telefon: 05321234567",
    }
    redactor = LiveEvidenceRedactor()
    redactor.collect(payload)
    redacted = redactor.redact(payload)
    for key in ("runtime_source_fingerprint", "runtime_source_fingerprint_current", "query_fingerprint", "source_snapshot_hash"):
        assert redacted[key] == digest
    assert "05321234567" not in redacted["phone"]
    assert "05321234567" not in redacted["answer"]
