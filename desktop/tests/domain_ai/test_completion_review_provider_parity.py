"""Different provider transports share the same review/actor authority boundary."""
from copy import deepcopy
from io import BytesIO
import json
from types import SimpleNamespace

import pytest
import requests

from AI.processors import cloud_runtime, local_transport, model_loop
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.runtime.answer_review import _COMPLETION_SCHEMA, review_answer


CONTROL = {"decision": "continue", "feedback": "Diğer mağazadaki kayıtlar henüz kontrol edilmedi."}


def payload(family, text, *, native_call=False):
    if family == "anthropic":
        blocks = [{"type": "text", "text": text}]
        if native_call:
            blocks.append({"type": "tool_use", "id": "forbidden", "name": "orders.query", "input": {}})
        return {"content": blocks, "stop_reason": "tool_use" if native_call else "end_turn"}
    if family == "gemini":
        parts = [{"text": text}]
        if native_call:
            parts.append({"functionCall": {"name": "orders.query", "args": {}}})
        return {"candidates": [{"content": {"parts": parts}, "finishReason": "STOP"}]}
    message = {"content": text}
    if native_call:
        message["tool_calls"] = [{"id": "forbidden", "type": "function", "function": {"name": "orders_query", "arguments": "{}"}}]
    return {"model": "local-selected", "choices": [{"message": message, "finish_reason": "tool_calls" if native_call else "stop"}]}


def transport(monkeypatch, family, text, *, native_call=False):
    sent = []
    reply = payload(family, text, native_call=native_call)
    if family != "local":
        def request(endpoint, **kwargs):
            sent.append({"endpoint": endpoint, **deepcopy(kwargs["payload"])})
            return deepcopy(reply)
        monkeypatch.setattr(cloud_runtime, "_provider_request_payload", request)
        model = cloud_runtime.build_provider_chat_client({
            "provider_code": family, "default_model": "claude-selected" if family == "anthropic" else "gemini-2.5-flash",
            "api_key": "synthetic", "is_enabled": True, "allow_model_fallback": False,
            "max_tokens": 8192, "reasoning_effort": "low"})
    else:
        class Session:
            def post(self, url, **kwargs):
                sent.append({"endpoint": url, **deepcopy(kwargs["json"])})
                response = requests.Response()
                response.status_code = 200
                response._content = json.dumps({"prompt": "the complete rendered prompt"} if url.endswith("/apply-template")
                    else {"tokens": [1, 2, 3]} if url.endswith("/tokenize") else reply).encode()
                if kwargs.get("stream"):
                    choice = reply["choices"][0]
                    frame = {"choices": [{"index": 0, "delta": choice["message"], "finish_reason": choice["finish_reason"]}]}
                    response.headers["Content-Type"] = "text/event-stream"
                    response.raw = BytesIO(("data: " + json.dumps(frame) + "\n\ndata: [DONE]\n\n").encode())
                    response._content = False
                return response
            def close(self):
                pass
        monkeypatch.setattr(local_transport.requests, "Session", Session)
        plan = SimpleNamespace(num_ctx=4096, max_tokens=128, reasoning_effort="low", sampling_defaults={},
            inference_timeout_seconds=2, tool_menu_limit=6, to_dict=lambda: {})
        model = local_transport.build_local_http_client(base_url="http://127.0.0.1:1234", model="local-selected", plan=plan)
    return model, sent


def state():
    result = AgentSessionState(goal="Diğer mağazaları da kontrol et")
    result.active_entities["model_loop"] = {"turn_started_step_count": 0}
    result.completed_steps.append(AgentTaskStep(index=1, step_id="call_1", prompt="One actual scoped read",
        tool_names=["orders.query"], status="completed", arguments={"api_account_ids": [1]},
        result_data={"tool_result": {"count": 0, "orders": [], "requested_api_account_ids": [1]}}))
    return result


@pytest.mark.parametrize("family", ["anthropic", "gemini", "local"])
def test_completion_review_without_final_text_preserves_candidate_and_returns_actor_feedback(monkeypatch, family):
    client, sent = transport(monkeypatch, family, json.dumps(CONTROL))
    assert client.resource_plan["final_answer_review_enabled"]
    assert not callable(getattr(client, "invoke_final_text", None))
    candidate = "İlk mağazada eşleşme yok; diğer mağazalar henüz okunmadı."
    answer, marker = review_answer(client, state(), candidate, sanitize=model_loop._preview)
    assert answer == candidate and marker["prose_reviewed"] and marker["continuation_required"]
    assert marker["continuation_feedback"] == CONTROL["feedback"]
    request = sent[-1]
    assert not any(key in request for key in ("tools", "tool_choice", "toolConfig"))
    if family == "local":
        assert [row["endpoint"].rsplit("/", 1)[-1] for row in sent] == ["apply-template", "tokenize", "completions"]
        assert request["model"] == "local-selected" and request["max_tokens"] == 128
        assert request["response_format"]["json_schema"]["schema"] == _COMPLETION_SCHEMA
        assert request["chat_template_kwargs"]["reasoning_effort"] == "low"


@pytest.mark.parametrize("family", ["anthropic", "gemini", "local"])
def test_unexpected_native_call_from_tool_free_review_never_becomes_actor_authority(monkeypatch, family):
    client, sent = transport(monkeypatch, family, json.dumps(CONTROL), native_call=True)
    candidate = "Bu mağazada 0 sonuç var."
    answer, marker = review_answer(client, state(), candidate, sanitize=model_loop._preview)
    assert answer == candidate and marker["review_status"] == "unavailable"
    assert not marker.get("continuation_required") and not marker["prose_reviewed"]
    assert len([row for row in sent if not row["endpoint"].endswith(("/apply-template", "/tokenize"))]) == 1


@pytest.mark.parametrize("family", ["anthropic", "gemini", "local"])
def test_reviewer_cannot_rewrite_the_answer_through_an_extra_control_field(monkeypatch, family):
    client, _ = transport(monkeypatch, family, json.dumps({"decision": "answer", "feedback": "", "answer": "Silindi."}))
    candidate = "Bu mağazada 0 sonuç var."
    answer, marker = review_answer(client, state(), candidate, sanitize=model_loop._preview)
    assert answer == candidate and marker["review_status"] == "unavailable"


def test_gemini_review_pins_previous_actual_model_without_catalog_or_fallback(monkeypatch):
    calls = []
    def request(endpoint, **kwargs):
        calls.append(endpoint)
        response = requests.Response()
        response.status_code = 429
        response._content = b'{"error":{"message":"model quota"}}'
        raise requests.HTTPError(response=response)
    monkeypatch.setattr(cloud_runtime, "_provider_request_payload", request)
    monkeypatch.setattr(cloud_runtime, "_fetch_gemini_catalog_model_ids", lambda **kwargs: pytest.fail("Review fetched a fallback catalog"))
    client = cloud_runtime._build_gemini_client(base_url="https://synthetic.test/v1beta", api_key="synthetic",
        model="gemini-primary", timeout=2, fallback_models=["gemini-sibling"], request_options={"allow_model_fallback": True})
    client.resource_plan = {"actual_model": "gemini-last-actual"}
    with pytest.raises(requests.HTTPError):
        client.invoke_completion_review("Check this candidate", schema=_COMPLETION_SCHEMA)
    assert len(calls) == 1 and "/models/gemini-last-actual:generateContent" in calls[0]
    assert client.resource_plan["requested_model"] == "gemini-last-actual"
    assert not client.resource_plan["fallback_used"] and not client.resource_plan["invocation_fallback_allowed"]
