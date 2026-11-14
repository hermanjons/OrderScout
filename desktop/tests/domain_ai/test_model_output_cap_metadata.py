"""A host planning default must not masquerade as a model's real output cap."""
from AI.processors.pipeline import _provider_model_to_dict
from AI.processors.model_routing import build_free_model_test_route
from AI.processors.task_runtime import _runtime_route_model_metadata, safe_agent_runtime_context


def test_catalogue_preserves_declared_output_limit_in_runtime_metadata():
    record = _provider_model_to_dict({"id": "minimax/minimax-m3.1-flash:free",
        "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools"],
        "context_length": 1000000, "top_provider": {"max_completion_tokens": 524288, "context_length": 1000000}},
        provider_code="openrouter")
    assert record["output_token_limit"] == 524288
    assert record["top_provider"]["max_completion_tokens"] == 524288
    route = build_free_model_test_route("openrouter", [record])
    candidate = route.to_dict()["models"][0]
    assert candidate["metadata"]["output_token_limit"] == 524288


def test_unknown_catalogue_limit_remains_unknown_beside_host_default():
    record = _provider_model_to_dict({"id": "minimax/minimax-m3.1-flash:free",
        "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools"]}, provider_code="openrouter")
    assert "output_token_limit" not in record
    route = build_free_model_test_route("openrouter", [record])
    candidate = route.to_dict()["models"][0]
    assert candidate["output_tokens"] == 2048
    assert candidate["metadata"]["output_token_limit"] is None


def test_checkpoint_route_does_not_promote_legacy_host_default_to_provider_cap():
    route = {"provider_code": "openrouter", "models": [{"model_id": "synthetic/model:free",
        "native_tool_calling": True, "output_tokens": 2048, "metadata": {}}]}
    metadata = _runtime_route_model_metadata(route, "synthetic/model:free")
    assert "output_token_limit" not in metadata
    route["models"][0]["metadata"]["output_token_limit"] = 524288
    assert _runtime_route_model_metadata(route, "synthetic/model:free")["output_token_limit"] == 524288


def test_checkpoint_preserves_actual_output_cap_and_explicit_reasoning_effort():
    context = safe_agent_runtime_context({"source": "cloud", "provider_id": 1, "model_name": "synthetic/model",
        "reasoning_effort": "max", "max_tokens": 2000, "api_key": "must-not-persist",
        "model_metadata": {"top_provider": {"max_completion_tokens": 524288}}})
    assert context["reasoning_effort"] == "max" and context["max_tokens"] == 2000
    assert context["model_metadata"]["output_token_limit"] == 524288
    assert "must-not-persist" not in str(context)
