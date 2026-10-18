from __future__ import annotations

import hashlib
import json
import time
from unittest.mock import patch

import requests
import pytest

from AI.processors import cloud_runtime, provider_adapters
from AI.processors.provider_adapters import (
    DEGRADATION_NATIVE_TOOLS,
    DEGRADATION_TEXT_GUARDED,
    capability_profile_from_record,
    evaluate_model_capability_gate,
    invoke_provider_planner,
    normalize_provider_error,
    record_provider_structured_contract_validation_failure,
    runtime_capability_profile,
)


class _Response:
    def __init__(
        self,
        payload: dict,
        *,
        status_code: int = 200,
        headers: dict | None = None,
    ):
        self._payload = payload
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.reason = "Too Many Requests" if status_code == 429 else "OK"
        self.url = "https://provider.example/v1/chat/completions"

    def json(self) -> dict:
        return dict(self._payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error",
                response=self,
            )


@pytest.mark.parametrize("provider", ["openrouter", "gemini"])
def test_native_structured_recovery_sends_schema_in_text(provider):
    schema = {"type": "object", "properties": {"requires_clarification": {"type": "boolean"}},
              "required": ["requires_clarification"], "additionalProperties": False}
    prompt = "Interpret the current user message."
    if provider == "openrouter":
        responses = [_Response({"choices": [{"message": {"content": ""}}]}),
            _Response({"choices": [{"message": {"content": '{"requires_clarification":false}'}}]})]
        model = "deepseek/deepseek-v4-flash"
    else:
        responses = [_Response({"error": {"message": "response schema not supported"}}, status_code=400),
            _Response({"candidates": [{"content": {"parts": [{"text": '{"requires_clarification":false}'}]}}]})]
        model = "gemini-2.5-flash"
    with patch.object(cloud_runtime.requests, "post", side_effect=responses) as post, patch.object(
        cloud_runtime, "_invocation_clock", side_effect=[100.0, 102.0, 110.0, 113.5]
    ):
        client = cloud_runtime.build_provider_chat_client({"provider_code": provider,
            "default_model": model, "api_key": "test-only", "is_enabled": True,
            "model_metadata": {"supported_parameters": ["response_format", "json_schema"]},
            "allow_model_fallback": False})
        assert json.loads(client.invoke_structured(prompt, schema=schema)) == {"requires_clarification": False}
    assert post.call_count == 2
    body = post.call_args_list[1].kwargs["json"]
    sent = body["messages"][0]["content"] if provider == "openrouter" else body["contents"][0]["parts"][0]["text"]
    marker = "GUARDED JSON RESPONSE CONTRACT (authoritative):"
    assert sent.startswith(prompt)
    assert sent.count(marker) == 1
    assert json.loads(sent.splitlines()[-1]) == schema
    assert provider_adapters.guarded_json_prompt(sent, schema) == sent
    outcomes = cloud_runtime.provider_invocation_provenance(client.resource_plan)["invocation_outcome_history"]
    assert [row["duration_seconds"] for row in outcomes] == [2.0, 3.5]
    assert [row["response_received"] for row in outcomes] == [False, True]


@pytest.fixture(autouse=True)
def _isolated_provider_contract_health_cache(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "ORDERSCOUT_PROVIDER_HEALTH_CACHE_PATH",
        str(tmp_path / "provider-contract-health.json"),
    )
    provider_adapters._STRUCTURED_CONTRACT_DEGRADATIONS.clear()
    yield
    provider_adapters._STRUCTURED_CONTRACT_DEGRADATIONS.clear()


def test_provider_post_has_a_true_wall_clock_deadline() -> None:
    def slow_post(*_args, **_kwargs):
        time.sleep(0.2)
        return _Response({"choices": [{"message": {"content": "late"}}]})

    started = time.monotonic()
    with patch.object(cloud_runtime.requests, "post", side_effect=slow_post):
        with pytest.raises(cloud_runtime.CloudTurnDeadlineExceeded):
            cloud_runtime._post_with_hard_wall_clock_timeout(
                "https://provider.example/v1/chat/completions",
                timeout=0.05,
                turn_deadline_limited=True,
                json={},
            )
    assert time.monotonic() - started < 0.15


def test_provider_phase_wall_clock_timeout_is_not_a_turn_deadline() -> None:
    def slow_post(*_args, **_kwargs):
        time.sleep(0.2)
        return _Response({"choices": [{"message": {"content": "late"}}]})

    with patch.object(cloud_runtime.requests, "post", side_effect=slow_post):
        with pytest.raises(requests.Timeout) as raised:
            cloud_runtime._post_with_hard_wall_clock_timeout(
                "https://provider.example/v1/chat/completions",
                timeout=0.05,
                turn_deadline_limited=False,
                json={},
            )
    assert type(raised.value) is requests.Timeout


def test_registry_covers_cloud_families_custom_and_local_llama_cpp() -> None:
    registry = cloud_runtime.provider_adapter_registry()

    assert {
        "openai",
        "openrouter",
        "groq",
        "together",
        "mistral",
        "custom",
        "anthropic",
        "gemini",
        "local",
        "llama_cpp",
    }.issubset(set(registry.codes()))
    assert registry.require("local").family == "llama_cpp"
    assert registry.require("llama_cpp") is registry.require("local")
    assert cloud_runtime.provider_adapter_for_record(
        {"provider_code": "future-provider", "endpoint_url": "https://future.example/v1"}
    ) is registry.require("custom")


def test_capability_negotiation_degrades_until_runtime_features_are_enabled() -> None:
    record = {
        "provider_code": "openrouter",
        "default_model": "vendor/tool-model:free",
        "model_metadata": {
            "supported_parameters": ["tools", "tool_choice", "response_format"],
            "context_length": 131_072,
            "max_output_tokens": 8_192,
        },
    }

    guarded = capability_profile_from_record(record)
    native = capability_profile_from_record(
        record,
        native_tool_runtime_enabled=True,
        structured_output_runtime_enabled=True,
    )

    assert guarded.native_tool_calling_available
    assert guarded.structured_output_available
    assert not guarded.native_tool_runtime_enabled
    assert guarded.degradation_mode == DEGRADATION_TEXT_GUARDED
    assert not guarded.external_write_planning_allowed
    assert native.degradation_mode == DEGRADATION_NATIVE_TOOLS
    assert native.external_write_planning_allowed


def test_capability_gate_distinguishes_model_plans_from_guarded_deterministic_prepare() -> None:
    guarded = capability_profile_from_record(
        {
            "provider_code": "local",
            "default_model": "model.gguf",
            "chat": True,
        }
    )
    model_plan = evaluate_model_capability_gate(
        guarded,
        prepare_write=True,
        external_write=True,
        decision_source="llm",
    )
    deterministic_plan = evaluate_model_capability_gate(
        guarded,
        prepare_write=True,
        external_write=True,
        decision_source="fallback",
    )
    chat_only = evaluate_model_capability_gate(
        {
            **guarded.to_dict(),
            "degradation_mode": "chat_only",
            "prepare_write_allowed": False,
        },
        prepare_write=True,
        external_write=False,
        decision_source="deterministic",
    )

    assert not model_plan.allowed
    assert model_plan.code == "external_write_model_plan_disabled"
    assert deterministic_plan.allowed
    assert not chat_only.allowed
    assert chat_only.code == "prepare_write_disabled"


def test_runtime_profile_uses_client_plan_then_record_for_rule_paths() -> None:
    def client(_prompt: str) -> str:
        return "ok"

    client.resource_plan = {
        "capability_profile": {
            "provider_code": "future",
            "model_id": "future-model",
            "degradation_mode": "chat_only",
            "prepare_write_allowed": False,
            "external_write_planning_allowed": False,
        }
    }

    selected = runtime_capability_profile(client, {"provider_code": "gemini"})
    local_rule = runtime_capability_profile(
        None,
        {"filename": "model.gguf", "local_path": "D:/models/model.gguf"},
    )

    assert selected["provider_code"] == "future"
    assert not selected["prepare_write_allowed"]
    assert local_rule["provider_code"] == "local"
    assert local_rule["degradation_mode"] == DEGRADATION_TEXT_GUARDED


def test_local_adapter_preserves_llama_runtime_plan_and_uses_guarded_contract() -> None:
    def local_client(_prompt: str) -> str:
        return "ok"

    local_client.runtime_name = "llama_cpp_server"
    local_client.model_name = "model.gguf"
    local_client.resource_plan = {"num_ctx": 8_192, "max_tokens": 1_024}

    with patch(
        "AI.processors.local_runtime.build_local_planner_client",
        return_value=local_client,
    ):
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "local",
                "filename": "model.gguf",
                "local_path": "D:/models/model.gguf",
                "is_enabled": True,
            }
        )

    assert client is local_client
    plan = client.resource_plan
    assert client.runtime_name == "llama_cpp_server"
    assert client.model_name == "model.gguf"
    assert plan["num_ctx"] == 8_192
    assert plan["provider_family"] == "llama_cpp"
    assert plan["profile"] == "local_provider"
    assert plan["degradation_mode"] == DEGRADATION_TEXT_GUARDED


def test_openrouter_uses_live_route_dict_and_recomputes_actual_model_profile() -> None:
    route = {
        "provider_code": "openrouter",
        "model_ids": ["vendor/requested:free", "vendor/fallback:free"],
        "models": [
            {
                "model_id": "vendor/requested:free",
                "native_tool_calling": True,
                "structured_output": True,
                "context_tokens": 65_536,
                "output_tokens": 2_048,
            },
            {
                "model_id": "vendor/fallback:free",
                "native_tool_calling": True,
                "structured_output": True,
                "context_tokens": 131_072,
                "output_tokens": 4_096,
            },
        ],
    }
    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=[
            _Response(
                {"error": {"message": "model rate limit reached"}},
                status_code=429,
            ),
            _Response({"choices": [{"message": {"content": "fallback ok"}}]}),
        ],
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "vendor/requested:free",
                "free_model_test_route": route,
                "model_metadata": {
                    "supported_parameters": ["tools", "response_format"],
                    "context_length": 65_536,
                },
                "native_tool_runtime_enabled": True,
                "structured_output_runtime_enabled": True,
                "is_enabled": True,
            }
        )
        assert client is not None
        assert client("hello") == "fallback ok"

    assert len(post_mock.call_args_list) == 2
    assert post_mock.call_args_list[1].kwargs["json"]["model"] == "vendor/fallback:free"
    plan = client.resource_plan
    assert plan["requested_model"] == "vendor/requested:free"
    assert plan["actual_model"] == "vendor/fallback:free"
    assert plan["fallback_used"]
    assert plan["capability_profile"]["model_id"] == "vendor/fallback:free"
    assert plan["capability_profile"]["context_tokens"] == 131_072
    assert plan["capability_profile"]["degradation_mode"] == DEGRADATION_NATIVE_TOOLS
    assert plan["capability_profile"]["external_write_planning_allowed"]


@pytest.mark.parametrize(
    ("explicit_timeout", "expected_timeout"),
    [
        (None, cloud_runtime.DEFAULT_CLOUD_REQUEST_TIMEOUT_SECONDS),
        (17.0, 17.0),
    ],
)
def test_cloud_provider_request_timeout_is_bounded_and_explicit_override_wins(
    explicit_timeout: float | None,
    expected_timeout: float,
) -> None:
    record = {
        "provider_code": "openrouter",
        "endpoint_url": "https://openrouter.ai/api/v1",
        "api_key": "secret",
        "default_model": "vendor/exact-model",
        "allow_model_fallback": False,
        "is_enabled": True,
    }
    with patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {"choices": [{"message": {"content": "ok"}}]}
        ),
    ) as post_mock:
        client = (
            cloud_runtime.build_provider_chat_client(record)
            if explicit_timeout is None
            else cloud_runtime.build_provider_chat_client(
                record,
                timeout=explicit_timeout,
            )
        )
        assert client is not None
        assert client("hello") == "ok"

    assert post_mock.call_args.kwargs["timeout"] == expected_timeout
    assert client.resource_plan["request_timeout_seconds"] == expected_timeout


def test_openrouter_exact_model_retries_transient_transport_without_fallback() -> None:
    exact_model = "deepseek/deepseek-v4-flash"
    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=[
            requests.RequestException("opaque upstream failure"),
            _Response(
                {"choices": [{"message": {"content": "recovered"}}]}
            ),
        ],
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": exact_model,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        assert client("hello") == "recovered"

    assert len(post_mock.call_args_list) == 2
    assert all(
        call.kwargs["json"]["model"] == exact_model
        for call in post_mock.call_args_list
    )
    plan = client.resource_plan
    assert plan["requested_model"] == exact_model
    assert plan["actual_model"] == exact_model
    assert plan["fallback_used"] is False
    assert plan["fallback_attempts"] == []
    assert plan["invocation_error_reason"] == ""
    assert plan["same_model_retry_events"] == [
        {
            "model": exact_model,
            "attempt": 1,
            "reason": "transport",
            "invocation_contract": "text",
            "prompt_sha256": hashlib.sha256(b"hello").hexdigest(),
        }
    ]
    assert plan["normalized_error_history"][0]["category"] == "transport"
    assert plan["normalized_error_history"][0]["retryable"] is True
    assert [row["attempt"] for row in plan["request_prompt_hashes"]] == [1, 2]


def test_openrouter_final_text_disables_optional_reasoning_and_keeps_output_headroom() -> None:
    exact_model = "deepseek/deepseek-v4-flash"
    with patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {"choices": [{"message": {"content": "verified final answer"}}]}
        ),
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": exact_model,
                "model_metadata": {
                    "supported_parameters": ["reasoning", "max_tokens"],
                    "reasoning": {
                        "mandatory": False,
                        "default_effort": "high",
                        "supported_efforts": ["high"],
                    },
                },
                "reasoning_effort": "auto",
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        assert client.invoke_final_text("summarize evidence") == "verified final answer"

    request_payload = post_mock.call_args.kwargs["json"]
    assert request_payload["model"] == exact_model
    assert request_payload["max_tokens"] == cloud_runtime.DEFAULT_FINAL_TEXT_MAX_TOKENS
    assert request_payload["reasoning"] == {
        "effort": "none",
        "exclude": True,
    }
    assert client.resource_plan["final_text_max_tokens"] == (
        cloud_runtime.DEFAULT_FINAL_TEXT_MAX_TOKENS
    )
    assert client.resource_plan["final_text_reasoning_disabled"] is True
    assert client.resource_plan["invocation_contract_history"][-1] == "final_text"
    assert client.resource_plan["actual_model"] == exact_model


def test_cloud_turn_deadline_clamps_request_to_remaining_wall_clock() -> None:
    client = cloud_runtime.build_provider_chat_client(
        {
            "provider_code": "openrouter",
            "endpoint_url": "https://openrouter.ai/api/v1",
            "api_key": "secret",
            "default_model": "vendor/exact-model",
            "allow_model_fallback": False,
            "is_enabled": True,
        }
    )
    assert client is not None

    with patch.object(
        cloud_runtime.time,
        "monotonic",
        side_effect=[100.0, 105.0],
    ), patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {"choices": [{"message": {"content": "ok"}}]}
        ),
    ) as post_mock:
        cloud_runtime.begin_provider_chat_turn(client, timeout=10.0)
        assert client("hello") == "ok"

    assert post_mock.call_args.kwargs["timeout"] == 5.0
    assert client.resource_plan["turn_timeout_seconds"] == 10.0
    assert client.resource_plan["turn_deadline_active"] is True


def test_cloud_turn_deadline_exhaustion_stops_before_network_request() -> None:
    client = cloud_runtime.build_provider_chat_client(
        {
            "provider_code": "openrouter",
            "endpoint_url": "https://openrouter.ai/api/v1",
            "api_key": "secret",
            "default_model": "vendor/exact-model",
            "allow_model_fallback": False,
            "is_enabled": True,
        }
    )
    assert client is not None

    with patch.object(
        cloud_runtime.time,
        "monotonic",
        side_effect=[100.0, 111.0],
    ), patch.object(cloud_runtime.requests, "post") as post_mock:
        cloud_runtime.begin_provider_chat_turn(client, timeout=10.0)
        with pytest.raises(cloud_runtime.CloudTurnDeadlineExceeded):
            client("hello")

    post_mock.assert_not_called()
    assert client.resource_plan["invocation_error_reason"] == (
        "turn_deadline_exceeded"
    )
    normalized = client.resource_plan["normalized_error_history"][-1]
    assert normalized["category"] == "turn_deadline"
    assert normalized["quota_scope"] == "runtime"
    assert normalized["retryable"] is False
    assert normalized["model_fallback_allowed"] is False
    assert client.resource_plan["fallback_blocked_reason"] == (
        "turn_deadline_exceeded"
    )


def test_structured_contract_reserves_shared_turn_budget_for_recovery() -> None:
    client = cloud_runtime.build_provider_chat_client(
        {
            "provider_code": "openrouter",
            "endpoint_url": "https://openrouter.ai/api/v1",
            "api_key": "secret",
            "default_model": "vendor/structured-budget-model",
            "model_metadata": {
                "supported_parameters": ["response_format", "json_schema"]
            },
            "structured_output_runtime_enabled": True,
            "allow_model_fallback": False,
            "is_enabled": True,
        }
    )
    assert client is not None

    with patch.object(
        cloud_runtime.time,
        "monotonic",
        side_effect=[100.0, 100.0],
    ), patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {"choices": [{"message": {"content": '{"mode":"chat"}'}}]}
        ),
    ) as post_mock:
        cloud_runtime.begin_provider_chat_turn(client, timeout=180.0)
        answer = client.invoke_structured(
            "classify",
            schema={"type": "object"},
        )

    assert json.loads(answer) == {"mode": "chat"}
    assert post_mock.call_args.kwargs["timeout"] == pytest.approx(30.0)
    assert client.resource_plan[
        "structured_output_recovery_reserve_seconds"
    ] == pytest.approx(150.0)


def test_openrouter_structured_timeout_degrades_once_to_guarded_exact_model() -> None:
    assert cloud_runtime.DEFAULT_GUARDED_JSON_MAX_TOKENS == 8192
    assert (
        cloud_runtime.DEFAULT_GUARDED_JSON_MAX_TOKENS
        == cloud_runtime.DEFAULT_STRUCTURED_OUTPUT_MAX_TOKENS
    )
    schema = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": ["mode"],
        "additionalProperties": False,
    }
    responses = [
        requests.Timeout("structured route timed out"),
        _Response(
            {"choices": [{"message": {"content": '{"mode":"inspect"}'}}]}
        ),
    ]
    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=responses,
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "vendor/structured-timeout-model",
                "model_metadata": {
                    "supported_parameters": [
                        "response_format",
                        "json_schema",
                    ]
                },
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = client.invoke_structured("classify", schema=schema)

    assert json.loads(answer) == {"mode": "inspect"}
    assert len(post_mock.call_args_list) == 2
    assert "response_format" in post_mock.call_args_list[0].kwargs["json"]
    assert "response_format" not in post_mock.call_args_list[1].kwargs["json"]
    assert (
        post_mock.call_args_list[1].kwargs["json"]["max_tokens"]
        == cloud_runtime.DEFAULT_GUARDED_JSON_MAX_TOKENS
    )
    assert client.resource_plan["structured_output_fallback_reason"] == (
        "structured_request_timeout"
    )


@pytest.mark.parametrize('limit_source,scope', [
    ('openrouter_key_limit', 'key_limit'),
    ('openrouter_workspace_budget', 'account'),
    ('openrouter_guardrail_budget', 'account'),
    ('', 'key_limit'),
])
def test_openrouter_spending_cap_is_billing_without_retry_fallback_or_private_remedy(limit_source, scope):
    response = _Response({'error': {'message': (
        'Key limit exceeded (total limit). Manage it using https://openrouter.ai/workspaces/default/keys/private-id '
        '$2.01 of $2.00 used; does not reset.'),
        'metadata': {'limit_source': limit_source, 'scope': 'api_key',
                     'remedy_hint': 'private account information'}}}, status_code=403)
    normalized = normalize_provider_error('openrouter', requests.HTTPError('403', response=response))
    assert normalized.category == 'billing' and normalized.quota_scope == scope
    assert not normalized.retryable and not normalized.model_fallback_allowed
    assert normalized.retry_after_seconds is None
    assert 'harcama sınırı' in normalized.safe_message
    assert 'private' not in json.dumps(normalized.to_dict())
    from AI.processors.task_runtime import provider_unavailable_answer
    answer = provider_unavailable_answer(normalized.to_dict())
    assert 'harcama sınırı' in answer and 'kimlik doğrulamasında' not in answer


def test_native_structured_output_has_plan_budget_and_recovers_partial_json_on_same_model():
    schema = {'type': 'object', 'properties': {'steps': {'type': 'array', 'items': {'type': 'object'}}},
              'required': ['steps'], 'additionalProperties': False}
    responses = [_Response({'choices': [{'message': {'content': '{"steps":[{"id":"first"'}}]}),
                 _Response({'choices': [{'message': {'content': '{"steps":[]}'}}]})]
    with patch.object(cloud_runtime.requests, 'post', side_effect=responses) as post:
        client = cloud_runtime.build_provider_chat_client({'provider_code': 'openrouter',
            'default_model': 'vendor/exact', 'api_key': 'test-only', 'is_enabled': True,
            'allow_model_fallback': False, 'model_metadata': {'supported_parameters': ['response_format', 'json_schema']}})
        assert json.loads(client.invoke_structured('Build a bounded current atomic plan', schema=schema)) == {'steps': []}
    assert post.call_count == 2
    assert post.call_args_list[0].kwargs['json']['max_tokens'] == cloud_runtime.DEFAULT_STRUCTURED_OUTPUT_MAX_TOKENS
    assert 'response_format' in post.call_args_list[0].kwargs['json']
    assert 'response_format' not in post.call_args_list[1].kwargs['json']
    assert all(call.kwargs['json']['model'] == 'vendor/exact' for call in post.call_args_list)
    assert client.resource_plan['structured_output_fallback_reason'] == 'invalid_structured_json'


@pytest.mark.parametrize('provider,status', [('openrouter', 401), ('other', 403)])
def test_spending_words_do_not_override_a_different_provider_or_authentication_status(provider, status):
    response = _Response({'error': {'message': 'Key limit exceeded (total limit)',
        'metadata': {'limit_source': 'openrouter_key_limit'}}}, status_code=status)
    normalized = normalize_provider_error(provider, requests.HTTPError(str(status), response=response))
    assert normalized.category == 'auth' and normalized.quota_scope == 'auth'


def test_openrouter_key_cap_stops_after_one_request_even_with_model_fallback_enabled():
    response = _Response({'error': {'message': 'Spending allowance exhausted',
        'metadata': {'limit_source': 'openrouter_key_limit'}}}, status_code=403)
    with patch.object(cloud_runtime.requests, 'post', return_value=response) as post:
        client = cloud_runtime.build_provider_chat_client({'provider_code': 'openrouter',
            'endpoint_url': 'https://openrouter.ai/api/v1', 'api_key': 'test-only',
            'default_model': 'vendor/requested', 'allow_model_fallback': True,
            'is_enabled': True})
        with pytest.raises(requests.HTTPError):
            client.invoke_final_text('Explain the current evidence')
    assert post.call_count == 1
    provenance = cloud_runtime.provider_invocation_provenance(client.resource_plan)
    assert provenance['final_error_category'] == 'billing'
    assert provenance['final_quota_scope'] == 'key_limit'
    assert provenance['any_model_fallback_used'] is False


def test_provider_quota_normalization_distinguishes_model_from_project_scope() -> None:
    model_response = _Response(
        {"error": {"message": "model rate limit reached"}},
        status_code=429,
    )
    project_response = _Response(
        {"error": {"message": "project quota exhausted"}},
        status_code=429,
    )
    model_error = requests.HTTPError("429", response=model_response)
    project_error = requests.HTTPError("429", response=project_response)

    model = normalize_provider_error("openrouter", model_error)
    project = normalize_provider_error("openrouter", project_error)

    assert model.category == "quota"
    assert model.quota_scope == "model"
    assert model.model_fallback_allowed
    assert project.category == "quota"
    assert project.quota_scope == "project"
    assert not project.model_fallback_allowed
    assert "project quota exhausted" not in project.safe_message


def test_gemini_per_project_per_model_quota_is_model_scope_with_safe_retry_delay() -> None:
    response = _Response(
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": (
                    "You exceeded your current quota, please check your "
                    "plan and billing details."
                ),
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": (
                                    "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                                ),
                                "quotaDimensions": {
                                    "model": "gemini-3.5-flash",
                                    "location": "global",
                                },
                            }
                        ],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "34s",
                    },
                ],
            }
        },
        status_code=429,
    )

    normalized = normalize_provider_error(
        "gemini",
        requests.HTTPError("429", response=response),
    )

    assert normalized.category == "quota"
    assert normalized.quota_scope == "model"
    assert normalized.model_fallback_allowed is True
    assert normalized.retry_after_seconds == 34
    assert "gemini-3.5-flash" not in normalized.safe_message


def test_unknown_429_fails_closed_instead_of_starting_model_roulette() -> None:
    normalized = normalize_provider_error(
        "openrouter",
        requests.HTTPError(
            "429",
            response=_Response(
                {"error": {"message": "Too many requests."}},
                status_code=429,
            ),
        ),
    )

    assert normalized.category == "quota"
    assert normalized.quota_scope == "unknown"
    assert normalized.model_fallback_allowed is False


def test_openrouter_free_tier_quota_does_not_claim_paid_account_is_exhausted() -> None:
    normalized = normalize_provider_error(
        "openrouter",
        requests.HTTPError(
            "429",
            response=_Response(
                {
                    "error": {
                        "message": (
                            "Rate limit exceeded: free-models-per-day quota "
                            "has been reached."
                        )
                    }
                },
                status_code=429,
            ),
        ),
    )

    assert normalized.category == "quota"
    assert normalized.quota_scope == "free_tier"
    assert normalized.model_fallback_allowed is False
    assert "free-models-per-day" not in normalized.safe_message


def test_openrouter_free_tier_quota_stops_free_siblings_without_pausing_paid_budget() -> None:
    route = {
        "provider_code": "openrouter",
        "model_ids": ["vendor/strong:free", "vendor/next:free"],
        "models": [],
    }
    with patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {
                "error": {
                    "message": "daily-free-limit reached for free models"
                }
            },
            status_code=429,
        ),
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "vendor/strong:free",
                "free_model_test_route": route,
                "is_enabled": True,
            }
        )
        assert client is not None
        with pytest.raises(requests.HTTPError):
            client("same state prompt")

    assert post_mock.call_count == 1
    outcome = client.resource_plan["invocation_outcome_history"][-1]
    assert outcome["quota_scope"] == "free_tier"
    assert outcome["model_fallback_allowed"] is False
    assert outcome["fallback_blocked_reason"] == "free_tier_quota"


def test_openrouter_model_quota_falls_through_same_state_route_and_keeps_error_evidence() -> None:
    route = {
        "provider_code": "openrouter",
        "model_ids": ["vendor/strong:free", "vendor/next:free"],
        "models": [],
    }
    responses = [
        _Response(
            {"error": {"message": "model rate limit reached"}},
            status_code=429,
            headers={"Retry-After": "12"},
        ),
        _Response(
            {"choices": [{"message": {"content": "same-state answer"}}]},
        ),
    ]
    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=responses,
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "vendor/strong:free",
                "free_model_test_route": route,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = client("same state prompt")

    assert answer == "same-state answer"
    assert post_mock.call_count == 2
    assert [
        call.kwargs["json"]["model"] for call in post_mock.call_args_list
    ] == ["vendor/strong:free", "vendor/next:free"]
    plan = client.resource_plan
    assert plan["actual_model"] == "vendor/next:free"
    assert plan["fallback_used"] is True
    outcome = plan["invocation_outcome_history"][-1]
    assert outcome["response_received"] is True
    assert outcome["fallback_used"] is True
    assert outcome["error_category"] == ""
    assert outcome["quota_scope"] == ""
    assert outcome["normalized_error_history"] == [
        {
            "provider_code": "openrouter",
            "category": "quota",
            "retryable": True,
            "quota_scope": "model",
            "status_code": 429,
            "safe_message": "Provider kota veya rate-limit yanıtı verdi.",
            "model_fallback_allowed": True,
            "retry_after_seconds": 12,
        }
    ]
    assert outcome["fallback_attempts"] == [
        {"model": "vendor/strong:free", "reason": "http_429"}
    ]
    provenance = cloud_runtime.provider_invocation_provenance(plan)
    assert provenance["final_model_response_received"] is True
    assert provenance["final_quota_scope"] == ""
    assert provenance["normalized_error_history"] == outcome[
        "normalized_error_history"
    ]


def test_openrouter_unknown_quota_stops_before_sibling_model() -> None:
    route = {
        "provider_code": "openrouter",
        "model_ids": ["vendor/strong:free", "vendor/next:free"],
        "models": [],
    }
    with patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {"error": {"message": "Too many requests."}},
            status_code=429,
        ),
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "vendor/strong:free",
                "free_model_test_route": route,
                "is_enabled": True,
            }
        )
        assert client is not None
        with pytest.raises(requests.HTTPError):
            client("same state prompt")

    assert post_mock.call_count == 1
    outcome = client.resource_plan["invocation_outcome_history"][-1]
    assert outcome["quota_scope"] == "unknown"
    assert outcome["model_fallback_allowed"] is False
    assert outcome["fallback_blocked_reason"] == "provider_quota"


def test_openrouter_upstream_auth_failure_is_model_route_unavailable_not_account_quota() -> None:
    response = _Response(
        {
            "error": {
                "message": "Provider returned error",
                "metadata": {
                    "is_byok": False,
                    "provider_name": "Google AI Studio",
                    "raw": json.dumps(
                        {
                            "error": {
                                "message": "API key not valid.",
                                "status": "INVALID_ARGUMENT",
                                "details": [{"reason": "API_KEY_INVALID"}],
                            }
                        }
                    ),
                    "previous_errors": ["upstream quota was unavailable"],
                },
            }
        },
        status_code=400,
    )

    normalized = normalize_provider_error(
        "openrouter",
        requests.HTTPError("400", response=response),
    )

    assert normalized.category == "model_unavailable"
    assert normalized.quota_scope == "model"
    assert normalized.retryable
    assert normalized.model_fallback_allowed
    assert "API key" not in normalized.safe_message


def test_openrouter_project_quota_pauses_route_without_trying_next_model() -> None:
    route = {
        "provider_code": "openrouter",
        "model_ids": ["vendor/requested:free", "vendor/fallback:free"],
        "models": [],
    }
    with patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {"error": {"message": "project quota exhausted"}},
            status_code=429,
        ),
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "vendor/requested:free",
                "free_model_test_route": route,
                "is_enabled": True,
            }
        )
        assert client is not None
        with pytest.raises(requests.HTTPError):
            client("same state prompt")

    assert post_mock.call_count == 1
    plan = client.resource_plan
    assert plan["quota_scope"] == "project"
    assert plan["fallback_blocked_reason"] == "provider_quota"
    assert plan["fallback_used"] is False
    assert plan["actual_model"] == ""
    assert plan["normalized_error_history"][0]["model_fallback_allowed"] is False


def test_openrouter_native_fallback_skips_incompatible_model_and_preserves_prompt_state() -> None:
    route = {
        "provider_code": "openrouter",
        "model_ids": [
            "vendor/requested:free",
            "vendor/text-only:free",
            "vendor/tool-fallback:free",
        ],
        "models": [
            {
                "model_id": "vendor/text-only:free",
                "native_tool_calling": False,
                "structured_output": False,
                "context_tokens": 65_536,
                "output_tokens": 2_048,
            },
            {
                "model_id": "vendor/tool-fallback:free",
                "native_tool_calling": True,
                "structured_output": True,
                "context_tokens": 131_072,
                "output_tokens": 4_096,
            },
        ],
    }
    state_prompt = json.dumps(
        {
            "message_index": 47,
            "selection": ["order-a", "order-b"],
            "pending_action": {"operation_id": "labels.create.prepare"},
        },
        sort_keys=True,
    )
    tool_decision = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "orders_ready_to_ship_count",
                                "arguments": "{}",
                            }
                        }
                    ]
                }
            }
        ]
    }
    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=[
            _Response(
                {"error": {"message": "model rate limit reached"}},
                status_code=429,
            ),
            _Response(tool_decision),
        ],
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "vendor/requested:free",
                "free_model_test_route": route,
                "model_metadata": {
                    "supported_parameters": ["tools", "tool_choice", "response_format"],
                    "context_length": 65_536,
                },
                "native_tool_runtime_enabled": True,
                "structured_output_runtime_enabled": True,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = client.invoke_tools(
            state_prompt,
            tools=[
                {
                    "name": "orders.ready_to_ship_count",
                    "description": "Count ready orders",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
        )

    assert answer
    assert [call.kwargs["json"]["model"] for call in post_mock.call_args_list] == [
        "vendor/requested:free",
        "vendor/tool-fallback:free",
    ]
    assert all(
        call.kwargs["json"]["messages"][0]["content"] == state_prompt
        for call in post_mock.call_args_list
    )
    plan = client.resource_plan
    expected_prompt_hash = hashlib.sha256(state_prompt.encode("utf-8")).hexdigest()
    assert plan["request_prompt_hashes"] == [
        {"model": "vendor/requested:free", "prompt_sha256": expected_prompt_hash},
        {"model": "vendor/tool-fallback:free", "prompt_sha256": expected_prompt_hash},
    ]
    assert plan["actual_model"] == "vendor/tool-fallback:free"
    assert plan["fallback_used"] is True
    assert plan["capability_profile"]["native_tool_runtime_enabled"] is True
    assert plan["fallback_attempts"] == [
        {"model": "vendor/requested:free", "reason": "http_429"},
        {
            "model": "vendor/text-only:free",
            "reason": "capability_incompatible:native_tools",
        },
    ]


def test_openai_compatible_structured_planner_sends_strict_schema_on_wire() -> None:
    schema = {
        "type": "object",
        "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
        "required": ["steps"],
        "additionalProperties": False,
    }
    with patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {"choices": [{"message": {"content": '{"steps":["orders.recent"]}'}}]}
        ),
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openai",
                "endpoint_url": "https://api.example.test/v1",
                "api_key": "secret",
                "default_model": "structured-model",
                "model_metadata": {
                    "supported_parameters": ["response_format", "json_schema"]
                },
                "native_tool_runtime_enabled": False,
                "structured_output_runtime_enabled": True,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = client.invoke_structured("plan", schema=schema)

    assert json.loads(answer) == {"steps": ["orders.recent"]}
    payload = post_mock.call_args.kwargs["json"]
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "orderscout_planner_output",
            "strict": True,
            "schema": schema,
        },
    }
    profile = client.resource_plan["capability_profile"]
    assert profile["structured_output_runtime_enabled"]
    assert not profile["native_tool_runtime_enabled"]
    assert profile["degradation_mode"] == "structured_plan"
    assert client.resource_plan["last_invocation_contract"] == "structured_output"


def test_openrouter_structured_http_400_retries_guarded_json_on_same_exact_model() -> None:
    schema = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": ["mode"],
        "additionalProperties": False,
    }
    responses = [
        _Response({"error": {"message": "response_format rejected"}}, status_code=400),
        _Response({"choices": [{"message": {"content": '{"mode":"chat"}'}}]}),
    ]
    with patch.object(cloud_runtime.requests, "post", side_effect=responses) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "google/gemma-test:free",
                "model_metadata": {
                    "supported_parameters": [
                        "response_format",
                        "json_schema",
                        "reasoning",
                    ],
                    "reasoning": {"mandatory": False},
                },
                "native_tool_runtime_enabled": True,
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = client.invoke_structured("classify", schema=schema)

    assert json.loads(answer) == {"mode": "chat"}
    assert len(post_mock.call_args_list) == 2
    first_payload = post_mock.call_args_list[0].kwargs["json"]
    second_payload = post_mock.call_args_list[1].kwargs["json"]
    assert first_payload["model"] == "google/gemma-test:free"
    assert second_payload["model"] == "google/gemma-test:free"
    assert "response_format" in first_payload
    assert "response_format" not in second_payload
    assert second_payload["reasoning"] == {"effort": "none", "exclude": True}
    assert client.resource_plan["actual_model"] == "google/gemma-test:free"
    assert client.resource_plan["fallback_used"] is False
    assert client.resource_plan["structured_output_fallback_reason"] == "http_400"
    assert client.resource_plan["structured_output_fallback_contract"] == (
        "same_exact_model_json_text_guarded"
    )
    assert client.resource_plan["invocation_contract_history"] == [
        "structured_output",
        "json_text_guarded",
    ]


def test_openrouter_structured_empty_uses_guarded_json_on_same_exact_model() -> None:
    schema = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": ["mode"],
        "additionalProperties": False,
    }
    responses = [
        _Response({"choices": [{"message": {"content": ""}}]}),
        _Response({"choices": [{"message": {"content": '{"mode":"chat"}'}}]}),
    ]
    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=responses,
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "deepseek/deepseek-v4-flash",
                "model_metadata": {
                    "supported_parameters": [
                        "response_format",
                        "json_schema",
                        "reasoning",
                    ],
                    "reasoning": {"mandatory": False},
                },
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = client.invoke_structured("classify", schema=schema)

    assert json.loads(answer) == {"mode": "chat"}
    assert len(post_mock.call_args_list) == 2
    assert all(
        call.kwargs["json"]["model"] == "deepseek/deepseek-v4-flash"
        for call in post_mock.call_args_list
    )
    assert "response_format" in post_mock.call_args_list[0].kwargs["json"]
    assert "response_format" not in post_mock.call_args_list[1].kwargs["json"]
    assert client.resource_plan["fallback_used"] is False
    assert client.resource_plan["structured_output_fallback_reason"] == (
        "empty_structured_response"
    )
    assert client.resource_plan["structured_output_fallback_contract"] == (
        "same_exact_model_json_text_guarded"
    )
    assert client.resource_plan["invocation_contract_history"] == [
        "structured_output",
        "json_text_guarded",
    ]
    assert client.resource_plan["same_model_empty_retry_history"] == []


def test_planner_reuses_guarded_contract_after_same_client_structured_recovery() -> None:
    schema = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": ["mode"],
        "additionalProperties": False,
    }
    responses = [
        _Response({"choices": [{"message": {"content": ""}}]}),
        _Response({"choices": [{"message": {"content": '{"mode":"inspect"}'}}]}),
        _Response({"choices": [{"message": {"content": '{"mode":"plan"}'}}]}),
    ]
    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=responses,
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "deepseek/deepseek-v4-flash",
                "model_metadata": {
                    "supported_parameters": [
                        "response_format",
                        "json_schema",
                        "reasoning",
                    ],
                    "reasoning": {"mandatory": False},
                },
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        first = invoke_provider_planner(
            client,
            "interpret",
            response_schema=schema,
        )
        second = invoke_provider_planner(
            client,
            "plan",
            response_schema=schema,
        )

    assert json.loads(first) == {"mode": "inspect"}
    assert json.loads(second) == {"mode": "plan"}
    assert post_mock.call_count == 3
    assert "response_format" in post_mock.call_args_list[0].kwargs["json"]
    assert "response_format" not in post_mock.call_args_list[1].kwargs["json"]
    assert "response_format" not in post_mock.call_args_list[2].kwargs["json"]
    assert client.resource_plan["structured_output_bypassed"] is True
    assert client.resource_plan["structured_output_bypass_reason"] == (
        "empty_response"
    )
    assert client.resource_plan["structured_output_bypass_contract"] == (
        "same_exact_model_json_text_guarded"
    )
    assert client.resource_plan["invocation_contract_history"] == [
        "structured_output",
        "json_text_guarded",
        "json_text_guarded",
    ]
    assert client.resource_plan["fallback_used"] is False


def test_structured_contract_health_carries_across_rebuilt_clients_in_process() -> None:
    schema = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": ["mode"],
        "additionalProperties": False,
    }
    record = {
        "id": 991337,
        "provider_code": "openrouter",
        "endpoint_url": "https://openrouter.ai/api/v1",
        "api_key": "secret",
        "default_model": "vendor/process-contract-health-model",
        "model_metadata": {
            "supported_parameters": ["response_format", "json_schema"]
        },
        "structured_output_runtime_enabled": True,
        "allow_model_fallback": False,
        "is_enabled": True,
    }
    responses = [
        _Response({"choices": [{"message": {"content": ""}}]}),
        _Response(
            {"choices": [{"message": {"content": '{"mode":"inspect"}'}}]}
        ),
        _Response(
            {"choices": [{"message": {"content": '{"mode":"plan"}'}}]}
        ),
    ]

    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=responses,
    ) as post_mock:
        first_client = cloud_runtime.build_provider_chat_client(record)
        assert first_client is not None
        first = invoke_provider_planner(
            first_client,
            "interpret",
            response_schema=schema,
        )

        second_client = cloud_runtime.build_provider_chat_client(record)
        assert second_client is not None
        second = invoke_provider_planner(
            second_client,
            "plan",
            response_schema=schema,
        )

    assert json.loads(first) == {"mode": "inspect"}
    assert json.loads(second) == {"mode": "plan"}
    assert post_mock.call_count == 3
    assert "response_format" in post_mock.call_args_list[0].kwargs["json"]
    assert "response_format" not in post_mock.call_args_list[1].kwargs["json"]
    assert "response_format" not in post_mock.call_args_list[2].kwargs["json"]
    assert second_client.resource_plan[
        "structured_output_health_cache_hit"
    ] is True
    assert second_client.resource_plan["structured_output_bypassed"] is True


def test_structured_contract_health_carries_across_fresh_process_cache(
    tmp_path,
    monkeypatch,
) -> None:
    cache_path = tmp_path / "provider-contract-health.json"
    monkeypatch.setenv(
        "ORDERSCOUT_PROVIDER_HEALTH_CACHE_PATH",
        str(cache_path),
    )
    provider_adapters._STRUCTURED_CONTRACT_DEGRADATIONS.clear()
    schema = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": ["mode"],
        "additionalProperties": False,
    }
    record = {
        "id": 991338,
        "provider_code": "openrouter",
        "endpoint_url": "https://openrouter.ai/api/v1",
        "api_key": "secret",
        "default_model": "vendor/persistent-contract-health-model",
        "model_metadata": {
            "supported_parameters": ["response_format", "json_schema"]
        },
        "structured_output_runtime_enabled": True,
        "allow_model_fallback": False,
        "is_enabled": True,
    }
    responses = [
        _Response({"choices": [{"message": {"content": ""}}]}),
        _Response(
            {"choices": [{"message": {"content": '{"mode":"inspect"}'}}]}
        ),
        _Response(
            {"choices": [{"message": {"content": '{"mode":"plan"}'}}]}
        ),
    ]

    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=responses,
    ) as post_mock:
        first_client = cloud_runtime.build_provider_chat_client(record)
        assert first_client is not None
        first = invoke_provider_planner(
            first_client,
            "interpret",
            response_schema=schema,
        )
        assert cache_path.is_file()

        # A fresh Python process starts with an empty in-memory dictionary but
        # keeps the value-free hashed contract-health record in AppData.
        provider_adapters._STRUCTURED_CONTRACT_DEGRADATIONS.clear()
        second_client = cloud_runtime.build_provider_chat_client(record)
        assert second_client is not None
        second = invoke_provider_planner(
            second_client,
            "plan",
            response_schema=schema,
        )

    assert json.loads(first) == {"mode": "inspect"}
    assert json.loads(second) == {"mode": "plan"}
    assert post_mock.call_count == 3
    assert "response_format" in post_mock.call_args_list[0].kwargs["json"]
    assert "response_format" not in post_mock.call_args_list[1].kwargs["json"]
    assert "response_format" not in post_mock.call_args_list[2].kwargs["json"]
    assert second_client.resource_plan[
        "structured_output_health_cache_hit"
    ] is True
    assert second_client.resource_plan["structured_output_bypassed"] is True
    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    serialized = json.dumps(persisted, ensure_ascii=False)
    assert "secret" not in serialized
    assert "persistent-contract-health-model" not in serialized
    assert "interpret" not in serialized
    provider_adapters._STRUCTURED_CONTRACT_DEGRADATIONS.clear()


def test_failed_guarded_recovery_still_persists_native_contract_failure(
    tmp_path,
    monkeypatch,
) -> None:
    cache_path = tmp_path / "provider-contract-health.json"
    monkeypatch.setenv(
        "ORDERSCOUT_PROVIDER_HEALTH_CACHE_PATH",
        str(cache_path),
    )
    provider_adapters._STRUCTURED_CONTRACT_DEGRADATIONS.clear()
    schema = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": ["mode"],
        "additionalProperties": False,
    }
    record = {
        "id": 991339,
        "provider_code": "openrouter",
        "endpoint_url": "https://openrouter.ai/api/v1",
        "api_key": "secret",
        "default_model": "vendor/native-failure-before-guard-model",
        "model_metadata": {
            "supported_parameters": ["response_format", "json_schema"]
        },
        "structured_output_runtime_enabled": True,
        "allow_model_fallback": False,
        "is_enabled": True,
    }
    responses = [
        _Response({"choices": [{"message": {"content": ""}}]}),
        cloud_runtime.CloudTurnDeadlineExceeded("guard deadline"),
        _Response(
            {"choices": [{"message": {"content": '{"mode":"plan"}'}}]}
        ),
    ]

    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=responses,
    ) as post_mock:
        first_client = cloud_runtime.build_provider_chat_client(record)
        assert first_client is not None
        with pytest.raises(cloud_runtime.CloudTurnDeadlineExceeded):
            invoke_provider_planner(
                first_client,
                "interpret",
                response_schema=schema,
            )
        assert cache_path.is_file()

        provider_adapters._STRUCTURED_CONTRACT_DEGRADATIONS.clear()
        second_client = cloud_runtime.build_provider_chat_client(record)
        assert second_client is not None
        second = invoke_provider_planner(
            second_client,
            "plan",
            response_schema=schema,
        )

    assert json.loads(second) == {"mode": "plan"}
    assert post_mock.call_count == 3
    assert "response_format" in post_mock.call_args_list[0].kwargs["json"]
    assert "response_format" not in post_mock.call_args_list[1].kwargs["json"]
    assert "response_format" not in post_mock.call_args_list[2].kwargs["json"]
    assert second_client.resource_plan[
        "structured_output_health_cache_hit"
    ] is True
    assert second_client.resource_plan["structured_output_bypassed"] is True
    assert second_client.resource_plan["structured_output_bypass_reason"] == (
        "empty_structured_response"
    )
    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "empty_structured_response" in json.dumps(persisted)
    provider_adapters._STRUCTURED_CONTRACT_DEGRADATIONS.clear()


def test_openrouter_structured_upstream_auth_400_does_not_retry_same_broken_route() -> None:
    response = _Response(
        {
            "error": {
                "message": "Provider returned error",
                "metadata": {
                    "is_byok": False,
                    "provider_name": "Google AI Studio",
                    "raw": '{"error":{"status":"INVALID_ARGUMENT",'
                    '"message":"API key not valid.",'
                    '"details":[{"reason":"API_KEY_INVALID"}]}}',
                },
            }
        },
        status_code=400,
    )
    with patch.object(cloud_runtime.requests, "post", return_value=response) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "google/gemma-broken:free",
                "model_metadata": {
                    "supported_parameters": ["response_format", "json_schema"],
                },
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        with pytest.raises(requests.HTTPError):
            client.invoke_structured(
                "classify",
                schema={"type": "object", "additionalProperties": True},
            )

    assert post_mock.call_count == 1
    plan = client.resource_plan
    assert plan["invocation_contract_history"] == ["structured_output"]
    assert plan["normalized_error_history"][0]["category"] == "model_unavailable"
    assert plan["fallback_blocked_reason"] == ""


def test_openai_compatible_native_tool_planner_maps_safe_wire_names_back() -> None:
    with patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "orders_ready_to_ship",
                                        "arguments": '{"period":"today"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ),
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "openrouter",
                "endpoint_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "default_model": "vendor/native-model",
                "model_metadata": {
                    "supported_parameters": ["tools", "tool_choice", "response_format"]
                },
                "native_tool_runtime_enabled": True,
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = client.invoke_tools(
            "plan",
            tools=[
                {
                    "name": "orders.ready_to_ship",
                    "description": "Ready orders",
                    "parameters": {
                        "type": "object",
                        "properties": {"period": {"type": "string"}},
                        "required": ["period"],
                        "additionalProperties": False,
                    },
                }
            ],
        )

    assert json.loads(answer) == {
        "mode": "tool",
        "tool": "orders.ready_to_ship",
        "arguments": {"period": "today"},
    }
    payload = post_mock.call_args.kwargs["json"]
    assert payload["tool_choice"] == "auto"
    assert payload["tools"][0]["function"]["name"] == "orders_ready_to_ship"
    assert "strict" not in payload["tools"][0]["function"]


def test_anthropic_adapter_wires_native_tools_and_forced_structured_output() -> None:
    responses = [
        _Response(
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu-1",
                        "name": "orders_count",
                        "input": {"period": "today"},
                    }
                ],
                "stop_reason": "tool_use",
            }
        ),
        _Response(
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu-2",
                        "name": "orderscout_structured_output",
                        "input": {"steps": [{"id": "orders.recent"}]},
                    }
                ],
                "stop_reason": "tool_use",
            }
        ),
    ]
    with patch.object(cloud_runtime.requests, "post", side_effect=responses) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "anthropic",
                "api_key": "secret",
                "default_model": "claude-test",
                "native_tool_runtime_enabled": True,
                "structured_output_runtime_enabled": True,
                "is_enabled": True,
            }
        )
        assert client is not None
        tool_answer = client.invoke_tools(
            "plan",
            tools=[
                {
                    "name": "orders.count",
                    "description": "Count orders",
                    "parameters": {
                        "type": "object",
                        "properties": {"period": {"type": "string"}},
                        "required": ["period"],
                        "additionalProperties": False,
                    },
                }
            ],
        )
        structured_answer = client.invoke_structured(
            "task plan",
            schema={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"id": {"type": "string"}},
                            "required": ["id"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["steps"],
                "additionalProperties": False,
            },
        )

    assert json.loads(tool_answer)["tool"] == "orders.count"
    assert json.loads(structured_answer) == {"steps": [{"id": "orders.recent"}]}
    first_payload = post_mock.call_args_list[0].kwargs["json"]
    second_payload = post_mock.call_args_list[1].kwargs["json"]
    assert first_payload["tools"][0]["input_schema"]["required"] == ["period"]
    assert first_payload["tool_choice"] == {"type": "auto"}
    assert second_payload["tool_choice"] == {
        "type": "tool",
        "name": "orderscout_structured_output",
    }
    assert client.resource_plan["last_invocation_contract"] == "structured_output"
    assert client.resource_plan["invocation_contract_history"] == [
        "native_tools",
        "structured_output",
    ]
    assert client.resource_plan["requested_model"] == "claude-test"
    assert client.resource_plan["actual_model"] == "claude-test"
    assert client.resource_plan["fallback_used"] is False
    assert len(client.resource_plan["request_prompt_hashes"]) == 1
    profile = client.resource_plan["capability_profile"]
    assert profile["native_tool_runtime_enabled"]
    assert profile["structured_output_runtime_enabled"]
    assert profile["degradation_mode"] == DEGRADATION_NATIVE_TOOLS


def test_gemini_adapter_wires_structured_output_and_native_tools() -> None:
    schema = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["steps"],
        "additionalProperties": False,
    }
    responses = [
        _Response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": '{"steps":["orders.recent"]}'}]
                        }
                    }
                ]
            }
        ),
        _Response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "orders_ready_to_ship",
                                        "args": {"period": "today"},
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        ),
    ]
    with patch.object(cloud_runtime.requests, "post", side_effect=responses) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "gemini",
                "api_key": "secret",
                "default_model": "gemini-3.1-flash-lite",
                "model_metadata": {
                    "supported_parameters": ["tools", "response_schema"]
                },
                "native_tool_runtime_enabled": True,
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        structured_answer = client.invoke_structured("task plan", schema=schema)
        tool_answer = client.invoke_tools(
            "plan",
            tools=[
                {
                    "name": "orders.ready_to_ship",
                    "description": "Ready orders",
                    "parameters": {
                        "type": "object",
                        "properties": {"period": {"type": "string"}},
                        "required": ["period"],
                        "additionalProperties": False,
                    },
                }
            ],
        )

    assert json.loads(structured_answer) == {"steps": ["orders.recent"]}
    assert json.loads(tool_answer) == {
        "mode": "tool",
        "tool": "orders.ready_to_ship",
        "arguments": {"period": "today"},
    }
    structured_payload = post_mock.call_args_list[0].kwargs["json"]
    tool_payload = post_mock.call_args_list[1].kwargs["json"]
    assert structured_payload["generationConfig"]["responseFormat"] == {
        "text": {
            "mimeType": "APPLICATION_JSON",
            "schema": schema,
        }
    }
    assert (
        structured_payload["generationConfig"]["maxOutputTokens"]
        == cloud_runtime.DEFAULT_STRUCTURED_OUTPUT_MAX_TOKENS
    )
    assert tool_payload["tools"][0]["functionDeclarations"][0]["name"] == (
        "orders_ready_to_ship"
    )
    assert tool_payload["toolConfig"]["functionCallingConfig"] == {"mode": "AUTO"}
    profile = client.resource_plan["capability_profile"]
    assert profile["native_tool_runtime_enabled"]
    assert profile["structured_output_runtime_enabled"]
    assert profile["degradation_mode"] == DEGRADATION_NATIVE_TOOLS
    assert client.resource_plan["last_invocation_contract"] == "native_tools"
    assert client.resource_plan["invocation_contract_history"] == [
        "structured_output",
        "native_tools",
    ]


def test_gemini_multi_invocation_provenance_keeps_prior_success_after_final_429() -> None:
    responses = [
        _Response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": '{"mode":"inspect"}'}]
                        }
                    }
                ]
            }
        ),
        _Response(
            {"error": {"message": "quota exhausted"}},
            status_code=429,
        ),
    ]
    with patch.object(cloud_runtime.requests, "post", side_effect=responses):
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "gemini",
                "api_key": "secret",
                "default_model": "gemini-3-flash-preview",
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        first = client.invoke_structured(
            "classify",
            schema={"type": "object", "additionalProperties": True},
        )
        with pytest.raises(requests.HTTPError):
            client("synthesize")

    assert json.loads(first) == {"mode": "inspect"}
    plan = client.resource_plan
    assert plan["actual_model"] == ""
    assert plan["invocation_error_reason"] == "http_429"
    assert plan["model_response_count"] == 1
    assert plan["any_model_response_received"] is True
    assert plan["final_model_response_received"] is False
    assert plan["last_successful_actual_model"] == "gemini-3-flash-preview"
    assert plan["successful_actual_models"] == ["gemini-3-flash-preview"]
    outcomes = plan["invocation_outcome_history"]
    assert len(outcomes) == 2
    assert outcomes[0]["contract"] == "structured_output"
    assert outcomes[0]["requested_model"] == "gemini-3-flash-preview"
    assert outcomes[0]["actual_model"] == "gemini-3-flash-preview"
    assert outcomes[0]["response_received"] is True
    assert outcomes[0]["error_reason"] == ""
    assert outcomes[0]["fallback_used"] is False
    assert outcomes[0]["normalized_error_history"] == []
    assert outcomes[1]["contract"] == "text"
    assert outcomes[1]["requested_model"] == "gemini-3-flash-preview"
    assert outcomes[1]["actual_model"] == ""
    assert outcomes[1]["response_received"] is False
    assert outcomes[1]["error_reason"] == "http_429"
    assert outcomes[1]["fallback_used"] is False
    assert outcomes[1]["error_category"] == "quota"
    assert outcomes[1]["quota_scope"] == "unknown"
    assert outcomes[1]["status_code"] == 429
    assert outcomes[1]["model_fallback_allowed"] is False
    assert outcomes[1]["fallback_blocked_reason"] == "provider_quota"
    assert outcomes[1]["normalized_error_history"]
    provenance = cloud_runtime.provider_invocation_provenance(plan)
    assert provenance["requested_model"] == "gemini-3-flash-preview"
    assert provenance["actual_model"] == "gemini-3-flash-preview"
    assert provenance["last_successful_actual_model"] == "gemini-3-flash-preview"
    assert provenance["final_actual_model"] == ""
    assert provenance["model_response_count"] == 1
    assert provenance["any_model_response_received"] is True
    assert provenance["final_model_response_received"] is False
    assert provenance["final_invocation_error_reason"] == "http_429"
    assert provenance["final_error_category"] == "quota"
    assert provenance["final_quota_scope"] == "unknown"
    assert provenance["final_status_code"] == 429
    assert provenance["final_model_fallback_allowed"] is False
    assert provenance["final_fallback_blocked_reason"] == "provider_quota"
    assert provenance["any_model_fallback_used"] is False


def test_provider_provenance_keeps_legacy_single_response_compatible() -> None:
    provenance = cloud_runtime.provider_invocation_provenance(
        {
            "requested_model": "legacy-requested",
            "actual_model": "legacy-actual",
            "fallback_used": True,
            "invocation_error_reason": "",
        }
    )

    assert provenance["requested_model"] == "legacy-requested"
    assert provenance["actual_model"] == "legacy-actual"
    assert provenance["final_actual_model"] == "legacy-actual"
    assert provenance["model_response_count"] == 1
    assert provenance["any_model_response_received"] is True
    assert provenance["final_model_response_received"] is True
    assert provenance["any_model_fallback_used"] is True


def test_provider_turn_plan_reports_only_new_invocations_from_shared_client() -> None:
    shared_plan = {
        "provider_code": "gemini",
        "requested_model": "gemini-test",
        "actual_model": "",
        "invocation_error_reason": "http_429",
        "invocation_contract_history": [
            "structured_output",
            "text",
            "structured_output",
        ],
        "invocation_outcome_history": [
            {
                "contract": "structured_output",
                "requested_model": "gemini-test",
                "actual_model": "gemini-test",
                "response_received": True,
                "error_reason": "",
                "fallback_used": False,
            },
            {
                "contract": "text",
                "requested_model": "gemini-test",
                "actual_model": "gemini-test",
                "response_received": True,
                "error_reason": "",
                "fallback_used": False,
            },
            {
                "contract": "structured_output",
                "requested_model": "gemini-test",
                "actual_model": "",
                "response_received": False,
                "error_reason": "http_429",
                "fallback_used": False,
            },
        ],
    }

    turn_plan = cloud_runtime.provider_invocation_turn_plan(
        shared_plan,
        outcome_start=2,
        contract_start=2,
    )

    assert turn_plan["model_invocation_attempted"] is True
    assert turn_plan["model_response_count"] == 0
    assert turn_plan["any_model_response_received"] is False
    assert turn_plan["final_model_response_received"] is False
    assert turn_plan["actual_model"] == ""
    assert turn_plan["last_successful_actual_model"] == ""
    assert turn_plan["invocation_error_reason"] == "http_429"
    assert turn_plan["invocation_contract_history"] == ["structured_output"]
    assert len(turn_plan["invocation_outcome_history"]) == 1

    no_call_plan = cloud_runtime.provider_invocation_turn_plan(
        shared_plan,
        outcome_start=3,
        contract_start=3,
    )
    assert no_call_plan["model_invocation_attempted"] is False
    assert no_call_plan["model_response_count"] == 0
    assert no_call_plan["any_model_response_received"] is False
    assert no_call_plan["actual_model"] == ""
    assert no_call_plan["invocation_outcome_history"] == []


def test_gemini_text_extractor_ignores_thought_summary_parts() -> None:
    payload = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"text": "internal summary", "thought": True},
                        {"text": '{"steps":[]}'},
                    ]
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "thoughtsTokenCount": 30,
            "totalTokenCount": 45,
        },
    }

    assert cloud_runtime._extract_gemini_text(payload) == '{"steps":[]}'
    metadata = cloud_runtime._gemini_response_metadata(payload)
    assert metadata == {
        "finish_reason": "STOP",
        "part_count": 2,
        "thought_part_count": 1,
        "text_part_count": 2,
        "prompt_token_count": 10,
        "candidate_token_count": 5,
        "thought_token_count": 30,
        "total_token_count": 45,
    }


def test_gemini_25_structured_output_uses_legacy_generate_content_fields() -> None:
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
        "additionalProperties": False,
    }
    with patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {
                "candidates": [
                    {"content": {"parts": [{"text": '{"count":2}'}]}}
                ]
            }
        ),
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "gemini",
                "api_key": "secret",
                "default_model": "gemini-2.5-flash-lite",
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = client.invoke_structured("count", schema=schema)

    assert json.loads(answer) == {"count": 2}
    generation_config = post_mock.call_args.kwargs["json"]["generationConfig"]
    assert generation_config["responseMimeType"] == "application/json"
    assert generation_config["responseSchema"] == {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
    }
    assert "responseFormat" not in generation_config


def test_gemini_structured_http_400_retries_text_on_exact_model() -> None:
    schema = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["steps"],
        "additionalProperties": False,
    }
    responses = [
        _Response({"error": {"message": "schema rejected"}}, status_code=400),
        _Response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": '{"steps":["orders.fetch.prepare"]}'}
                            ]
                        }
                    }
                ]
            }
        ),
    ]
    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=responses,
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "gemini",
                "api_key": "secret",
                "default_model": "gemini-3.1-flash-lite",
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = client.invoke_structured("task plan", schema=schema)

    assert json.loads(answer) == {"steps": ["orders.fetch.prepare"]}
    assert post_mock.call_count == 2
    structured_payload = post_mock.call_args_list[0].kwargs["json"]
    text_payload = post_mock.call_args_list[1].kwargs["json"]
    assert "responseFormat" in structured_payload["generationConfig"]
    assert "responseFormat" not in text_payload["generationConfig"]
    assert (
        text_payload["generationConfig"]["maxOutputTokens"]
        == cloud_runtime.DEFAULT_GUARDED_JSON_MAX_TOKENS
    )
    assert client.resource_plan["actual_model"] == "gemini-3.1-flash-lite"
    assert client.resource_plan["fallback_used"] is False
    assert client.resource_plan["structured_output_fallback_reason"] == "http_400"
    assert client.resource_plan["invocation_contract_history"] == [
        "structured_output",
        "text",
    ]


def test_gemini_structured_empty_retries_text_on_same_exact_model() -> None:
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
        "additionalProperties": False,
    }
    empty = _Response(
        {"candidates": [{"content": {"parts": [{"text": ""}]}}]}
    )
    valid = _Response(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"count":2}'}]
                    }
                }
            ]
        }
    )
    with patch.object(
        cloud_runtime.requests,
        "post",
        side_effect=[empty, valid],
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "gemini",
                "api_key": "secret",
                "default_model": "gemini-2.5-flash",
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = client.invoke_structured("count", schema=schema)

    assert json.loads(answer) == {"count": 2}
    assert post_mock.call_count == 2
    assert "responseMimeType" in (
        post_mock.call_args_list[0].kwargs["json"]["generationConfig"]
    )
    assert "responseMimeType" not in (
        post_mock.call_args_list[1].kwargs["json"]["generationConfig"]
    )
    assert client.resource_plan["fallback_used"] is False
    assert client.resource_plan["structured_output_fallback_reason"] == (
        "empty_structured_response"
    )
    assert client.resource_plan["structured_output_fallback_contract"] == (
        "same_exact_model_json_text_guarded"
    )
    assert client.resource_plan["invocation_contract_history"] == [
        "structured_output",
        "text",
    ]


def test_gemini_hosted_gemma_does_not_inherit_gemini_tool_authority() -> None:
    client = cloud_runtime.build_provider_chat_client(
        {
            "provider_code": "gemini",
            "api_key": "secret",
            "default_model": "gemma-3-27b-it",
            "native_tool_runtime_enabled": True,
            "structured_output_runtime_enabled": True,
            "allow_model_fallback": False,
            "is_enabled": True,
        }
    )

    assert client is not None
    profile = client.resource_plan["capability_profile"]
    assert not profile["native_tool_calling_available"]
    assert not profile["structured_output_available"]
    assert not profile["native_tool_runtime_enabled"]
    assert not profile["structured_output_runtime_enabled"]
    assert profile["degradation_mode"] == DEGRADATION_TEXT_GUARDED


def test_gemini_hosted_gemma_can_plan_through_guarded_json_text() -> None:
    schema = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["steps"],
        "additionalProperties": False,
    }
    with patch.object(
        cloud_runtime.requests,
        "post",
        return_value=_Response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": '{"steps":["orders.summary"]}'}
                            ]
                        }
                    }
                ]
            }
        ),
    ) as post_mock:
        client = cloud_runtime.build_provider_chat_client(
            {
                "provider_code": "gemini",
                "api_key": "secret",
                "default_model": "gemma-4-31b-it",
                "native_tool_runtime_enabled": True,
                "structured_output_runtime_enabled": True,
                "allow_model_fallback": False,
                "is_enabled": True,
            }
        )
        assert client is not None
        answer = invoke_provider_planner(
            client,
            "Return the typed plan as one JSON object.",
            response_schema=schema,
        )

    assert json.loads(answer) == {"steps": ["orders.summary"]}
    assert post_mock.call_count == 1
    assert "models/gemma-4-31b-it:generateContent" in post_mock.call_args.args[0]
    generation_config = post_mock.call_args.kwargs["json"]["generationConfig"]
    assert "responseMimeType" not in generation_config
    assert "responseFormat" not in generation_config
    assert (
        generation_config["maxOutputTokens"]
        == cloud_runtime.DEFAULT_GUARDED_JSON_MAX_TOKENS
    )
    assert client.resource_plan["actual_model"] == "gemma-4-31b-it"
    assert client.resource_plan["fallback_used"] is False
    assert client.resource_plan["invocation_contract_history"] == [
        "json_text_guarded"
    ]


def test_supported_wired_features_auto_enable_without_hidden_runtime_flags() -> None:
    records = [
        {
            "provider_code": "gemini",
            "api_key": "secret",
            "default_model": "gemini-3.1-flash-lite",
            "allow_model_fallback": False,
            "is_enabled": True,
        },
        {
            "provider_code": "openrouter",
            "api_key": "secret",
            "default_model": "vendor/tool-model:free",
            "model_metadata": {
                "supported_parameters": ["tools", "response_format"]
            },
            "allow_model_fallback": False,
            "is_enabled": True,
        },
        {
            "provider_code": "anthropic",
            "api_key": "secret",
            "default_model": "claude-test",
            "is_enabled": True,
        },
    ]

    for record in records:
        client = cloud_runtime.build_provider_chat_client(record)
        assert client is not None
        profile = client.resource_plan["capability_profile"]
        assert profile["native_tool_runtime_enabled"], record["provider_code"]
        assert profile["structured_output_runtime_enabled"], record["provider_code"]
        assert profile["degradation_mode"] == DEGRADATION_NATIVE_TOOLS


def test_explicit_runtime_feature_opt_out_remains_authoritative() -> None:
    client = cloud_runtime.build_provider_chat_client(
        {
            "provider_code": "gemini",
            "api_key": "secret",
            "default_model": "gemini-3.1-flash-lite",
            "native_tool_runtime_enabled": False,
            "structured_output_runtime_enabled": False,
            "allow_model_fallback": False,
            "is_enabled": True,
        }
    )

    assert client is not None
    profile = client.resource_plan["capability_profile"]
    assert not profile["native_tool_runtime_enabled"]
    assert not profile["structured_output_runtime_enabled"]
    assert profile["degradation_mode"] == DEGRADATION_TEXT_GUARDED


def test_record_flags_without_a_wired_client_cannot_grant_runtime_authority() -> None:
    profile = runtime_capability_profile(
        None,
        {
            "provider_code": "anthropic",
            "default_model": "claude-test",
            "native_tool_runtime_enabled": True,
            "structured_output_runtime_enabled": True,
        },
    )

    assert profile["native_tool_calling_available"]
    assert profile["structured_output_available"]
    assert not profile["native_tool_runtime_enabled"]
    assert not profile["structured_output_runtime_enabled"]
    assert profile["degradation_mode"] == DEGRADATION_TEXT_GUARDED
    assert not profile["external_write_planning_allowed"]


def test_planner_invocation_prefers_wired_native_then_structured_contracts() -> None:
    calls: list[str] = []

    def client(_prompt: str) -> str:
        calls.append("text")
        return '{"mode":"answer","response":"text"}'

    def invoke_tools(_prompt: str, *, tools: list[dict]) -> str:
        calls.append(f"tools:{tools[0]['name']}")
        return '{"mode":"tool","tool":"orders.count","arguments":{}}'

    def invoke_structured(_prompt: str, *, schema: dict) -> str:
        calls.append(f"structured:{schema.get('type')}")
        return '{"steps":[{"id":"orders.recent"}]}'

    client.invoke_tools = invoke_tools
    client.invoke_structured = invoke_structured
    client.resource_plan = {
        "capability_profile": {
            "native_tool_runtime_enabled": True,
            "structured_output_runtime_enabled": True,
        }
    }

    native = invoke_provider_planner(
        client,
        "plan",
        tools=[{"name": "orders.count", "parameters": {"type": "object"}}],
    )
    client.resource_plan["capability_profile"]["native_tool_runtime_enabled"] = False
    structured = invoke_provider_planner(
        client,
        "task",
        response_schema={"type": "object"},
    )

    assert json.loads(native)["tool"] == "orders.count"
    assert json.loads(structured)["steps"][0]["id"] == "orders.recent"
    assert calls == ["tools:orders.count", "structured:object"]


def test_text_guarded_planner_receives_the_authoritative_json_schema_in_prompt() -> None:
    captured: dict[str, object] = {}

    def client(_prompt: str) -> str:
        raise AssertionError("Guarded JSON method should own this invocation")

    def invoke_json_text(prompt: str, *, schema: dict) -> str:
        captured["prompt"] = prompt
        captured["schema"] = schema
        return '{"decision":"visible_requested"}'

    client.invoke_json_text = invoke_json_text
    client.resource_plan = {
        "capability_profile": {
            "native_tool_runtime_enabled": False,
            "structured_output_runtime_enabled": False,
        }
    }
    schema = {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["visible_requested", "internal_only"],
            }
        },
        "required": ["decision"],
        "additionalProperties": False,
    }

    answer = invoke_provider_planner(
        client,
        "Classify the projection field.",
        response_schema=schema,
    )

    assert json.loads(answer) == {"decision": "visible_requested"}
    assert captured["schema"] == schema
    prompt = str(captured["prompt"])
    assert prompt.startswith("Classify the projection field.")
    assert "GUARDED JSON RESPONSE CONTRACT (authoritative)" in prompt
    assert '"required":["decision"]' in prompt
    assert '"additionalProperties":false' in prompt


def test_bounded_repair_can_prefer_guarded_json_without_retrying_structured() -> None:
    calls: list[str] = []

    def client(_prompt: str) -> str:
        calls.append("text")
        return '{}'

    def invoke_structured(_prompt: str, *, schema: dict) -> str:
        calls.append(f"structured:{schema.get('type')}")
        return '{"source":"structured"}'

    def invoke_json_text(prompt: str, *, schema: dict) -> str:
        calls.append(f"guarded:{schema.get('type')}")
        assert "GUARDED JSON RESPONSE CONTRACT (authoritative)" in prompt
        return '{"source":"guarded"}'

    client.invoke_structured = invoke_structured
    client.invoke_json_text = invoke_json_text
    client.resource_plan = {
        "capability_profile": {
            "native_tool_runtime_enabled": True,
            "structured_output_runtime_enabled": True,
        }
    }

    answer = invoke_provider_planner(
        client,
        "Repair only the malformed JSON.",
        response_schema={"type": "object"},
        prefer_guarded_json=True,
    )

    assert json.loads(answer) == {"source": "guarded"}
    assert calls == ["guarded:object"]


def test_schema_invalid_structured_contract_is_bypassed_for_same_client() -> None:
    calls: list[str] = []

    def client(_prompt: str) -> str:
        calls.append("text")
        return '{}'

    def invoke_structured(_prompt: str, *, schema: dict) -> str:
        calls.append(f"structured:{schema.get('type')}")
        return "not-json"

    def invoke_json_text(prompt: str, *, schema: dict) -> str:
        calls.append(f"guarded:{schema.get('type')}")
        assert "GUARDED JSON RESPONSE CONTRACT (authoritative)" in prompt
        return '{"mode":"inspect"}'

    client.invoke_structured = invoke_structured
    client.invoke_json_text = invoke_json_text
    client.resource_plan = {
        "requested_model": "deepseek/deepseek-v4-flash",
        "last_invocation_contract": "structured_output",
        "capability_profile": {
            "native_tool_runtime_enabled": True,
            "structured_output_runtime_enabled": True,
        },
    }

    recorded = record_provider_structured_contract_validation_failure(
        client,
        "planner response has no complete JSON payload",
    )
    answer = invoke_provider_planner(
        client,
        "Create the next typed contract.",
        response_schema={"type": "object"},
    )

    assert recorded is True
    assert json.loads(answer) == {"mode": "inspect"}
    assert calls == ["guarded:object"]
    assert client.resource_plan["structured_output_bypassed"] is True
    assert client.resource_plan["structured_output_bypass_reason"] == (
        "planner response has no complete JSON payload"
    )
    failure = client.resource_plan["structured_output_validation_failure"]
    assert failure["requested_model"] == "deepseek/deepseek-v4-flash"
