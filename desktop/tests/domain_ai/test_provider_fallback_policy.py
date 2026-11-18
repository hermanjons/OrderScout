"""The selected cloud model is retried before any configured alternative, and its failure stays visible."""
from unittest.mock import patch

import pytest
import requests

from AI.processors import cloud_runtime

PRIMARY = "z-ai/selected-tool-model"
TOOLS = [{"name": "orders.query", "description": "Local orders.",
          "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}]


class FakeResponse:
    def __init__(self, payload, *, status_code=200, reason="OK"):
        self._payload = payload
        self.status_code = status_code
        self.reason = reason
        self.url = "https://openrouter.ai/api/v1/chat/completions"
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error", response=self)

    def json(self):
        return dict(self._payload)


def unavailable():
    return FakeResponse({"error": {"message": "upstream unavailable"}}, status_code=503, reason="Service Unavailable")


def answer(text):
    return FakeResponse({"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})


def client_for(**extra):
    return cloud_runtime.build_provider_chat_client({
        "provider_code": "openrouter", "endpoint_url": "https://openrouter.ai/api/v1", "api_key": "sk-or-test",
        "default_model": PRIMARY, "is_enabled": True,
        "model_metadata": {"supported_parameters": ["tools", "tool_choice"]}, **extra})


def posted_models(post_mock):
    return [call.kwargs["json"]["model"] for call in post_mock.call_args_list]


@pytest.mark.parametrize("contract", ["text", "native_tools"])
def test_openrouter_without_a_configured_route_never_calls_an_unselected_model(contract):
    limited = FakeResponse({"error": {"message": "model rate limit reached"}}, status_code=429,
                           reason="Too Many Requests")
    with patch.object(cloud_runtime.requests, "post", side_effect=[limited]) as post_mock:
        client = client_for()
        with pytest.raises(requests.HTTPError):
            client("Merhaba") if contract == "text" else client.invoke_tools("Merhaba", tools=TOOLS)
    assert posted_models(post_mock) == [PRIMARY]


def test_selected_model_gets_a_transient_retry_even_when_a_route_is_configured():
    with patch.object(cloud_runtime.requests, "post", side_effect=[unavailable(), answer("Merhaba!")]) as post_mock:
        client = client_for(fallback_models=["configured/no-tool-metadata:free"])
        assert client.invoke_tools("Merhaba", tools=TOOLS) == "Merhaba!"
    assert posted_models(post_mock) == [PRIMARY, PRIMARY]
    assert client.resource_plan["actual_model"] == PRIMARY
    assert client.resource_plan["fallback_used"] is False


def test_skipped_alternative_does_not_mask_the_selected_model_failure():
    with patch.object(cloud_runtime.requests, "post", side_effect=[unavailable(), unavailable()]) as post_mock:
        client = client_for(fallback_models=["configured/no-tool-metadata:free"])
        with pytest.raises(requests.HTTPError):
            client.invoke_tools("Merhaba", tools=TOOLS)
    assert posted_models(post_mock) == [PRIMARY, PRIMARY]
    plan = client.resource_plan
    assert plan["invocation_error_reason"] == "http_503"
    assert {"model": "configured/no-tool-metadata:free", "reason": "capability_incompatible:native_tools"} in plan[
        "fallback_attempts"]
