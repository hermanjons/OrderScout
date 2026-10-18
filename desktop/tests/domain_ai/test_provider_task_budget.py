"""Long agent work reserves time once; individual provider calls stay bounded."""
from unittest.mock import patch

import pytest

from AI.processors import cloud_runtime


def _client():
    return cloud_runtime.build_provider_chat_client({
        "provider_code": "custom", "endpoint_url": "https://provider.invalid/v1",
        "default_model": "test-model", "is_enabled": True, "allow_model_fallback": False,
    })


def test_task_deadline_is_based_on_original_turn_and_does_not_slide_on_replanning():
    client = _client()
    assert client is not None and callable(client.reserve_task_budget)
    with patch.object(cloud_runtime.time, "monotonic", return_value=100):
        cloud_runtime.begin_provider_chat_turn(client)
    with patch.object(cloud_runtime.time, "monotonic", return_value=160):
        client.reserve_task_budget(max_steps=8)
    assert client.turn_started_monotonic == 100
    assert client.turn_deadline_monotonic == 1000
    assert client.resource_plan["task_timeout_seconds"] == 900
    with patch.object(cloud_runtime.time, "monotonic", return_value=800):
        client.reserve_task_budget(max_steps=64)
        assert cloud_runtime._effective_provider_request_timeout(client, 120) == 120
    assert client.turn_deadline_monotonic == 1000
    with patch.object(cloud_runtime.time, "monotonic", return_value=970):
        assert cloud_runtime._effective_provider_request_timeout(client, 120) == 30
    with patch.object(cloud_runtime.time, "monotonic", return_value=1001):
        with pytest.raises(cloud_runtime.CloudTurnDeadlineExceeded):
            cloud_runtime._effective_provider_request_timeout(client, 120)


def test_new_chat_turn_does_not_inherit_previous_task_reservation():
    client = _client()
    with patch.object(cloud_runtime.time, "monotonic", return_value=100):
        cloud_runtime.begin_provider_chat_turn(client)
        client.reserve_task_budget(max_steps=8)
    with patch.object(cloud_runtime.time, "monotonic", return_value=1500):
        cloud_runtime.begin_provider_chat_turn(client)
    assert client.turn_deadline_monotonic == 1680
    assert client.resource_plan["task_budget_reserved"] is False
    assert client.resource_plan["task_deadline_active"] is False
    assert "task_timeout_seconds" not in client.resource_plan


def test_delegate_method_changes_actual_provider_deadline_instead_of_wrapper_attribute():
    from AI.processors.conversation_runtime import _CapturedClient

    client = _client()
    wrapped = _CapturedClient(client)
    with patch.object(cloud_runtime.time, "monotonic", return_value=100):
        cloud_runtime.begin_provider_chat_turn(client)
        wrapped.reserve_task_budget(max_steps=4)
    assert client.turn_deadline_monotonic == 820
    assert "turn_deadline_monotonic" not in vars(wrapped)


@pytest.mark.parametrize("value", [True, 0, -1, 65, 1.5, "8"])
def test_unbounded_or_invalid_step_limits_cannot_reserve_provider_time(value):
    client = _client()
    with pytest.raises(ValueError, match="task_step_budget_invalid"):
        client.reserve_task_budget(max_steps=value)
    assert "task_timeout_seconds" not in client.resource_plan
