"""The real private review hook requests control data without tool authority."""
from copy import deepcopy
import json

import pytest

from AI.processors import cloud_runtime, model_loop
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.runtime.answer_review import _COMPLETION_SCHEMA, review_answer
from AI.runtime.response_stream import ResponseStreamIncomplete


SELECTED, PREVIOUS = "synthetic/selected", "synthetic/previous-actual"


def client():
    metadata = {"supported_parameters": ["tools", "tool_choice", "reasoning", "structured_outputs"],
                "reasoning": {"supported_efforts": ["low", "high"]}}
    built = cloud_runtime.build_provider_chat_client({"provider_code": "openrouter", "default_model": SELECTED,
        "endpoint_url": "https://synthetic.test/v1", "api_key": "synthetic-test-key", "is_enabled": True,
        "model_metadata": metadata, "allow_model_fallback": True, "reasoning_effort": "low",
        "free_model_test_route": {"models": [{"model_id": PREVIOUS, "metadata": metadata}]}})
    built.resource_plan["final_answer_review_enabled"] = True
    return built


def source_state():
    state = AgentSessionState(goal="Bütün mağazaları kontrol et")
    state.active_entities["model_loop"] = {"turn_started_step_count": 0}
    state.completed_steps.append(AgentTaskStep(index=1, step_id="call_1", prompt="Read one store",
        tool_names=["orders.query"], status="completed", arguments={"api_account_ids": [1]},
        result_data={"tool_result": {"count": 0, "orders": [], "requested_api_account_ids": [1]}}))
    return state


def intercept(monkeypatch, result, *, native_call=False):
    sent = []
    def request(endpoint, **kwargs):
        sent.append({"endpoint": endpoint, "contract": kwargs["invocation_contract"], "payload": deepcopy(kwargs["payload"])})
        message = {"content": result if isinstance(result, str) else json.dumps(result)}
        if native_call:
            message["tool_calls"] = [{"id": "review-must-not-run", "type": "function",
                                      "function": {"name": "orders_query", "arguments": "{}"}}]
        return {"model": kwargs["payload"]["model"], "choices": [{"message": message,
            "finish_reason": "tool_calls" if native_call else "stop"}]}
    monkeypatch.setattr(cloud_runtime, "_provider_request_payload", request)
    return sent


@pytest.mark.parametrize("actual", [SELECTED, PREVIOUS])
def test_private_review_uses_exact_last_actual_model_and_has_no_tool_request_authority(monkeypatch, actual):
    control = {"decision": "answer", "feedback": ""}
    sent = intercept(monkeypatch, control)
    model = client()
    model.resource_plan["actual_model"] = actual
    result = model.invoke_completion_review("Review this synthetic answer", schema=_COMPLETION_SCHEMA)
    assert json.loads(result) == control and len(sent) == 1
    payload = sent[0]["payload"]
    assert sent[0]["contract"] == "completion_review"
    assert payload["model"] == actual and not payload.get("models")
    assert "tools" not in payload and payload["tool_choice"] == "none"
    assert payload["reasoning"]["effort"] == "low"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"] == _COMPLETION_SCHEMA
    assert not model.resource_plan["invocation_fallback_allowed"]


def test_structured_continue_returns_feedback_without_rewriting_the_actor_candidate(monkeypatch):
    feedback = "Diğer mağazalar okunmadı; bu kapsamın kayıtlarını da kontrol et."
    candidate = "Seçili mağazada eşleşme yok; diğer mağazaların sonucu henüz bilinmiyor."
    sent = intercept(monkeypatch, {"decision": "continue", "feedback": feedback})
    answer, marker = review_answer(client(), source_state(), candidate, sanitize=model_loop._preview)
    assert answer == candidate
    assert marker["prose_reviewed"] and marker["continuation_required"]
    assert marker["continuation_feedback"] == feedback and marker["review_status"] == "model_self_review"
    assert len(sent) == 1 and sent[0]["contract"] == "completion_review"


def test_structured_answer_decision_preserves_the_entire_806_character_actor_answer(monkeypatch):
    candidate = ("Müşterinin bütün mağazalardaki **8 siparişini** kontrol ettim.\n\n"
        "En yüksek tutarlı sipariş SYNTHETIC-8, toplamı **1.414,92 TL**; ürünleri iki sentetik kupa.\n\n"
        + "\n".join(f"{index}. SYNTHETIC-{index} — yerel mağaza kaydı, ürün kalemleri okundu." for index in range(1, 9))
        + "\n\nSipariş numaraları, tutarlar ve ürünler kayıtlı araç sonuçlarından doğrulandı. "*5)[:805]+"."
    assert len(candidate) == 806
    sent = intercept(monkeypatch, {"decision": "answer", "feedback": ""})
    answer, marker = review_answer(client(), source_state(), candidate, sanitize=model_loop._preview)
    assert answer == candidate and len(answer) == 806
    assert marker["prose_reviewed"] and not marker["continuation_required"] and not marker["review_changed"]
    assert "<tool_call>" not in answer
    assert len(sent) == 1 and "tools" not in sent[0]["payload"]
    assert "answer" not in sent[0]["payload"]["response_format"]["json_schema"]["schema"]["properties"]


@pytest.mark.parametrize("invalid", [
    {"decision": "execute", "feedback": "Run a tool"},
    {"decision": "continue", "feedback": ""},
    {"decision": "answer", "feedback": "", "answer": "Yalnız bir giriş cümlesi; asıl cevabı silme."},
])
def test_invalid_structured_review_is_unavailable_and_preserves_the_original_candidate(monkeypatch, invalid):
    sent = intercept(monkeypatch, invalid)
    original = "Modelin özgün aday yanıtı."
    answer, marker = review_answer(client(), source_state(), original, sanitize=model_loop._preview)
    assert answer == original and marker["prose_reviewed"] is False
    assert marker["review_status"] == "unavailable"
    assert not marker.get("continuation_required") and not marker.get("continuation_feedback")
    assert len(sent) == 1 and "tools" not in sent[0]["payload"]


def test_native_tool_call_in_review_response_is_rejected_without_model_fallback(monkeypatch):
    sent = intercept(monkeypatch, "", native_call=True)
    model = client()
    with pytest.raises(ResponseStreamIncomplete):
        model.invoke_completion_review("Synthetic review", schema=_COMPLETION_SCHEMA)
    assert sent and all(row["payload"]["model"] == SELECTED for row in sent)
    assert all("tools" not in row["payload"] for row in sent)
    assert not model.resource_plan["invocation_fallback_allowed"]
