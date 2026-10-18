from __future__ import annotations

from unittest.mock import patch

from AI.processors import pipeline as ai_pipeline
from AI.processors import orders_model_acceptance_catalog_cli
from AI.processors.model_routing import build_free_model_test_route, stable_state_hash
from Feedback.processors.pipeline import Result


class _Response:
    status_code = 200
    reason = "OK"
    url = "https://openrouter.ai/api/v1/models"

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return dict(self._payload)

    def raise_for_status(self) -> None:
        return None


def _record(
    model_id: str,
    *,
    tools: bool = False,
    structured: bool = False,
    context: int = 65_536,
    output: int = 2_048,
) -> dict:
    return {
        "id": model_id,
        "is_free": True,
        "capability_profile": {
            "chat": True,
            "native_tool_calling_available": tools,
            "structured_output_available": structured,
            "context_tokens": context,
            "output_tokens": output,
            "reasoning": {"supported": tools},
        },
    }


def test_live_free_route_ranks_capability_quality_reliability_and_excludes_ineligible() -> None:
    state = {"selection": ["shipment-1", "shipment-2"], "pending_action": "labels.prepare"}
    route = build_free_model_test_route(
        "openrouter",
        [
            _record("plain-free"),
            _record("tool-free", tools=True, structured=True),
            _record("tiny-free", tools=True, structured=True, context=4_096),
        ],
        state_payload=state,
        accessibility={
            "plain-free": {"accessible": True, "reliability_score": 1.0, "latency_ms": 50},
            "tool-free": {"accessible": True, "reliability_score": 0.8, "latency_ms": 200},
            "tiny-free": {"accessible": True},
        },
        quality={
            "plain-free": {"quality_score": 1.0},
            "tool-free": {"quality_score": 0.8},
        },
    )

    assert route.generated_from_live_catalog
    assert route.state_hash == stable_state_hash(state)
    assert route.model_ids == ("tool-free", "plain-free")
    assert not next(row for row in route.candidates if row.model_id == "tiny-free").eligible


def test_explicit_quality_tier_keeps_best_model_first_even_with_guarded_text_contract() -> None:
    route = build_free_model_test_route(
        "openrouter",
        [
            _record("strong-guarded", tools=True, structured=False),
            _record("weaker-structured", tools=True, structured=True),
        ],
        quality={
            "strong-guarded": {
                "quality_tier": 100,
                "quality_score": 1.0,
                "quality_source": "reviewed",
            },
            "weaker-structured": {
                "quality_tier": 90,
                "quality_score": 0.9,
                "quality_source": "reviewed",
            },
        },
    )

    assert route.model_ids == ("strong-guarded", "weaker-structured")
    assert route.candidates[0].metadata["quality_source"] == "reviewed"


def test_route_transition_preserves_state_and_distinguishes_model_from_provider_quota() -> None:
    state = {"selected": [1, 2, 3], "count": 3}
    route = build_free_model_test_route(
        "gemini",
        [_record("model-a", tools=True), _record("model-b")],
        state_payload=state,
    )

    model_fallback = route.transition_after_failure(
        current_model="model-a",
        quota_scope="model",
        reason="rate_limit",
        message_index=47,
        state_payload=state,
    )
    provider_pause = route.transition_after_failure(
        current_model="model-a",
        quota_scope="project",
        reason="quota_exhausted",
        message_index=48,
        state_payload=state,
    )
    unknown_pause = route.transition_after_failure(
        current_model="model-a",
        quota_scope="unknown",
        reason="unclassified_429",
        message_index=48,
        state_payload=state,
    )
    state_changed = route.transition_after_failure(
        current_model="model-a",
        quota_scope="model",
        reason="rate_limit",
        message_index=49,
        state_payload={"selected": [1], "count": 1},
    )

    assert model_fallback["status"] == "fallback_selected"
    assert model_fallback["next_model"] == "model-b"
    assert model_fallback["message_index"] == 47
    assert model_fallback["state_hash"] == route.state_hash
    assert provider_pause["status"] == "provider_paused"
    assert not provider_pause["next_model"]
    assert unknown_pause["status"] == "provider_paused"
    assert not unknown_pause["next_model"]
    assert state_changed["status"] == "blocked_state_changed"
    assert state_changed["expected_state_hash"] == route.state_hash


def test_provider_catalog_exposes_capabilities_and_dynamic_free_route() -> None:
    payload = {
        "data": [
            {
                "id": "vendor/plain:free",
                "pricing": {"prompt": "0", "completion": "0", "request": "0"},
                "context_length": 65_536,
                "supported_parameters": [],
            },
            {
                "id": "vendor/tools:free",
                "pricing": {"prompt": "0", "completion": "0", "request": "0"},
                "context_length": 131_072,
                "supported_parameters": ["tools", "response_format"],
            },
        ]
    }
    state = {"selection": ["package-7"], "count": 1}

    with patch.object(ai_pipeline.requests, "get", return_value=_Response(payload)):
        result = ai_pipeline.list_provider_models(
            provider_code="openrouter",
            endpoint_url="https://openrouter.ai/api/v1",
            api_key="secret",
            free_only=True,
            route_state=state,
        )

    assert result.success, result.message
    data = result.data or {}
    records = data["records"]
    route = data["free_model_test_route"]
    assert records[0]["capability_profile"]["provider_code"] == "openrouter"
    assert next(row for row in records if row["id"] == "vendor/tools:free")["capability_profile"][
        "native_tool_calling_available"
    ]
    assert route["generated_from_live_catalog"]
    assert route["state_hash"] == stable_state_hash(state)
    assert route["model_ids"][0] == "vendor/tools:free"


def test_live_openrouter_catalog_applies_central_free_quality_order_before_capability_score() -> None:
    payload = {
        "data": [
            {
                "id": "google/gemma-4-31b-it:free",
                "pricing": {"prompt": "0", "completion": "0", "request": "0"},
                "context_length": 262_144,
                "supported_parameters": [
                    "tools",
                    "tool_choice",
                    "response_format",
                    "structured_outputs",
                ],
            },
            {
                "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
                "pricing": {"prompt": "0", "completion": "0", "request": "0"},
                "context_length": 1_000_000,
                "supported_parameters": [
                    "tools",
                    "tool_choice",
                    "reasoning",
                    "reasoning_effort",
                ],
            },
        ]
    }

    with patch.object(ai_pipeline.requests, "get", return_value=_Response(payload)):
        result = ai_pipeline.list_provider_models(
            provider_code="openrouter",
            endpoint_url="https://openrouter.ai/api/v1",
            api_key="secret",
            free_only=True,
        )

    assert result.success, result.message
    route = (result.data or {})["free_model_test_route"]
    assert route["model_ids"] == [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "google/gemma-4-31b-it:free",
    ]
    assert route["models"][0]["quality_tier"] == 100


def test_live_gemini_catalog_applies_central_free_quality_order() -> None:
    payload = {
        "models": [
            {
                "name": "models/gemini-2.5-flash",
                "displayName": "Gemini 2.5 Flash",
                "supportedGenerationMethods": ["generateContent"],
                "inputTokenLimit": 1_048_576,
                "outputTokenLimit": 65_536,
            },
            {
                "name": "models/gemini-3.5-flash",
                "displayName": "Gemini 3.5 Flash",
                "supportedGenerationMethods": ["generateContent"],
                "inputTokenLimit": 1_048_576,
                "outputTokenLimit": 65_536,
            },
        ]
    }

    with patch.object(ai_pipeline.requests, "get", return_value=_Response(payload)):
        result = ai_pipeline.list_provider_models(
            provider_code="gemini",
            api_key="secret",
            free_only=True,
        )

    assert result.success, result.message
    route = (result.data or {})["free_model_test_route"]
    assert route["model_ids"] == ["gemini-3.5-flash", "gemini-2.5-flash"]
    assert route["models"][0]["quality_tier"] == 100


def test_acceptance_catalog_preserves_live_quality_route_order_without_secrets(
    tmp_path,
) -> None:
    records = [
        {
            "id": "google/gemma-4-31b-it:free",
            "is_free": True,
            "capability_profile": {
                "native_tool_calling_available": True,
                "structured_output_available": True,
                "reasoning": {"supported": True},
            },
        },
        {
            "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "is_free": True,
            "capability_profile": {
                "native_tool_calling_available": True,
                "structured_output_available": False,
                "reasoning": {"supported": True},
            },
        },
    ]
    route = {
        "provider_code": "openrouter",
        "generated_from_live_catalog": True,
        "state_hash": "state-hash",
        "model_ids": [
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "google/gemma-4-31b-it:free",
        ],
        "models": [
            {
                "model_id": "nvidia/nemotron-3-ultra-550b-a55b:free",
                "quality_tier": 100,
                "quality_score": 0.0,
                "metadata": {
                    "quality_source": "orderscout_user_selected_free_model_policy",
                    "quality_reviewed_at": "2026-07-27",
                },
            },
            {
                "model_id": "google/gemma-4-31b-it:free",
                "quality_tier": 80,
                "quality_score": 0.0,
                "metadata": {
                    "quality_source": "orderscout_user_selected_free_model_policy",
                    "quality_reviewed_at": "2026-07-27",
                },
            },
        ],
    }

    with patch.object(
        orders_model_acceptance_catalog_cli,
        "list_provider_accounts",
        return_value=Result.ok(
            "ok",
            data={
                "records": [
                    {
                        "id": 7,
                        "provider_code": "openrouter",
                        "is_enabled": True,
                    }
                ]
            },
        ),
    ), patch.object(
        orders_model_acceptance_catalog_cli,
        "get_provider_account",
        return_value=Result.ok(
            "ok",
            data={
                "record": {
                    "endpoint_url": "https://openrouter.ai/api/v1",
                    "api_key": "must-not-leak",
                }
            },
        ),
    ), patch.object(
        orders_model_acceptance_catalog_cli,
        "list_provider_models",
        return_value=Result.ok(
            "ok",
            data={
                "records": records,
                "free_model_test_route": route,
            },
        ),
    ):
        catalog = orders_model_acceptance_catalog_cli.build_catalog(
            artifact_dir=tmp_path
        )

    provider = catalog["providers"][0]
    assert catalog["secrets_included"] is False
    assert provider["preferred_free_model"] == (
        "nvidia/nemotron-3-ultra-550b-a55b:free"
    )
    assert [row["id"] for row in provider["models"]] == route["model_ids"]
    assert provider["models"][0]["quality_tier"] == 100
    assert "must-not-leak" not in str(catalog)
