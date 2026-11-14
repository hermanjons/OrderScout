"""Provider review opt-in and transparent headless response capture."""
from types import SimpleNamespace
from copy import deepcopy
import json

import pytest
import requests

from AI.processors import cloud_runtime
from AI.processors.conversation_runtime import _CapturedClient
from AI.runtime.provider_response import ProviderText


@pytest.mark.parametrize("has_final_text", [False, True])
def test_provider_factory_enables_review_only_with_callable_final_text(monkeypatch, has_final_text):
    def runtime(prompt):
        raise AssertionError("Building the client must not invoke the model")

    runtime.invoke_final_text = (lambda prompt: ProviderText("Reviewed")) if has_final_text else None
    record = {"provider_code": "synthetic", "default_model": "synthetic-model", "is_enabled": True}
    adapter = SimpleNamespace(family="synthetic",
        build_chat_client=lambda record, timeout: runtime,
        capability_profile=lambda record: cloud_runtime.capability_profile_from_record(record))
    monkeypatch.setattr(cloud_runtime, "provider_adapter_for_record", lambda record: adapter)

    result = cloud_runtime.build_provider_chat_client(record)

    assert result is runtime
    assert result.resource_plan["final_answer_review_enabled"] is has_final_text


def test_headless_capture_records_final_review_without_erasing_text_provenance():
    prompts = []
    literal = ProviderText('{"mode":"tool","tool":"orders.count","arguments":{}}')

    def runtime(prompt):
        raise AssertionError("Review must use the final text method")

    def final_text(prompt):
        prompts.append(prompt)
        return literal

    runtime.invoke_final_text = final_text
    runtime.model_name = "synthetic-model"
    runtime.resource_plan = {"final_answer_review_enabled": True}
    captured = _CapturedClient(runtime)

    answer = captured.invoke_final_text("Review the exact receipt facts")

    assert answer is literal and isinstance(answer, ProviderText)
    assert prompts == ["Review the exact receipt facts"]
    assert len(captured.responses) == 1
    assert captured.responses[0]["contract"] == "invoke_final_text"
    assert captured.responses[0]["response"] == literal
    assert captured.responses[0]["actual_model"] == "synthetic-model"


def _response(payload, status=200):
    response = requests.Response()
    response.status_code = status
    response.url = "https://provider.test/v1/chat/completions"
    response._content = json.dumps(payload).encode()
    return response


def test_exact_final_review_keeps_actual_model_and_never_enters_sibling_route(monkeypatch):
    replies = iter([
        _response({"error": {"message": "model rate limit"}}, 429),
        _response({"choices": [{"message": {"content": "Candidate"}}]}),
        _response({"error": {"message": "Synthetic temporary failure"}}, 503),
        _response({"error": {"message": "Synthetic temporary failure"}}, 503),
        _response({"error": {"message": "model rate limit"}}, 429),
        _response({"choices": [{"message": {"content": "Next normal answer"}}]}),
    ])
    sent = []

    def post(*args, **kwargs):
        sent.append(deepcopy(kwargs["json"]))
        return next(replies)

    monkeypatch.setattr(cloud_runtime.requests, "post", post)
    metadata = {"supported_parameters": ["tools", "tool_choice", "reasoning"]}
    runtime = cloud_runtime.build_openai_compatible_client(
        base_url="https://provider.test/v1", api_key="synthetic", provider_code="openrouter",
        model="primary:free", fallback_models=["actual:free", "unused:free"],
        model_metadata=metadata,
        fallback_model_metadata={"actual:free": {**metadata, "output_token_limit": 1024}},
        request_options={"max_tokens": 1536, "reasoning": {"effort": "high", "exclude": True}},
    )
    assert runtime("Synthetic primary") == "Candidate"
    assert runtime.resource_plan["actual_model"] == "actual:free"

    with pytest.raises(requests.HTTPError):
        runtime.invoke_final_text("Review Candidate", exact_model=True)

    assert [payload["model"] for payload in sent] == ["primary:free", "actual:free", "actual:free", "actual:free"]
    assert all(payload["tool_choice"] == "none" and payload["max_tokens"] == 1024 for payload in sent[2:])
    assert all(payload["reasoning"] == {"effort": "high", "exclude": True} for payload in sent[2:])
    assert runtime.resource_plan["requested_model"] == "actual:free"
    assert runtime.resource_plan["invocation_outcome_history"][-1]["fallback_used"] is False
    assert runtime.resource_plan["invocation_fallback_allowed"] is False

    # The exact review policy is local to that call; normal fallback survives.
    assert runtime("Next normal turn") == "Next normal answer"
    assert [payload["model"] for payload in sent[-2:]] == ["primary:free", "actual:free"]
    assert runtime.resource_plan["invocation_fallback_allowed"] is True


def test_exact_review_without_prior_actual_uses_selected_model(monkeypatch):
    sent = []

    def post(*args, **kwargs):
        sent.append(deepcopy(kwargs["json"]))
        return _response({"choices": [{"message": {"content": "Reviewed"}}]})

    monkeypatch.setattr(cloud_runtime.requests, "post", post)
    runtime = cloud_runtime.build_provider_chat_client({
        "provider_code": "openrouter", "endpoint_url": "https://provider.test/v1", "api_key": "synthetic",
        "default_model": "selected:free", "fallback_models": ["unused:free"], "is_enabled": True,
        "model_metadata": {"supported_parameters": ["tools", "tool_choice"]},
    })
    assert runtime.invoke_final_text("Review", exact_model=True) == "Reviewed"
    assert [payload["model"] for payload in sent] == ["selected:free"]
    assert runtime.resource_plan["invocation_outcome_history"][-1]["fallback_used"] is False


def test_review_auto_reasoning_keeps_provider_default_instead_of_low_shortcut(monkeypatch):
    sent = []
    def post(*args, **kwargs):
        sent.append(deepcopy(kwargs["json"]))
        return _response({"choices": [{"message": {"content": "Reviewed"}}]})
    monkeypatch.setattr(cloud_runtime.requests, "post", post)
    runtime = cloud_runtime.build_openai_compatible_client(
        base_url="https://provider.test/v1", api_key="synthetic", provider_code="openrouter", model="selected:free",
        model_metadata={"supported_parameters": ["tools", "reasoning"], "reasoning": {
            "mandatory": True, "supported": True, "efforts": ["low", "medium", "high", "max"], "default_effort": "max"}})
    assert runtime.invoke_final_text("Review", exact_model=True) == "Reviewed"
    assert (sent[0].get("reasoning") or {}).get("effort") in {None, "auto", "max"}
    assert runtime.resource_plan["final_text_reasoning_effort"] == "auto"
