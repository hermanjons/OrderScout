"""Long agent work reserves time once; individual provider calls stay bounded."""
import json as json_module
from types import SimpleNamespace
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


@pytest.fixture
def native_turn(tmp_path, monkeypatch):
    """Exercise the real captured client, native decoder and tool dispatcher."""
    from AI.processors import conversation_runtime, observation_artifacts, tools
    from AI.runtime.contracts import AgentTool
    from Feedback.processors.pipeline import Result

    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(cloud_runtime.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(observation_artifacts, "OBSERVATION_ARTIFACTS_ROOT", tmp_path / "observations")
    state = SimpleNamespace(clock=clock, requests=[], executed=[], reservations=[], decisions=[], elapsed=80.0,
                            after_response=None)
    client = cloud_runtime.build_provider_chat_client({
        "provider_code": "custom", "endpoint_url": "https://provider.invalid/v1",
        "default_model": "test-model", "is_enabled": True, "allow_model_fallback": False,
        "model_metadata": {"supported_parameters": ["tools", "tool_choice"]},
    })
    reserve = client.reserve_task_budget

    def reserve_once(**options):
        state.reservations.append((clock.now, options))
        reserve(**options)

    client.reserve_task_budget = reserve_once

    def read(*, index):
        state.executed.append((index, client.turn_deadline_monotonic))
        assert client.resource_plan["task_budget_reserved"] is True
        return Result.ok("Synthetic read completed.", data={"index": index})

    registry = {"example.read": AgentTool(name="example.read", description="Read a synthetic value.",
        parameters={"type": "object", "properties": {"index": {"type": "integer"}},
                    "required": ["index"], "additionalProperties": False}, handler=read)}
    monkeypatch.setattr(tools, "available_tools", lambda: registry)
    monkeypatch.setattr(tools, "registered_tools", lambda: registry)

    def post(url, *, json, timeout, **kwargs):
        payload = json
        state.requests.append({"at": clock.now, "deadline": client.turn_deadline_monotonic,
                               "timeout": timeout, "payload": payload})
        decision = state.decisions.pop(0)
        clock.now += state.elapsed
        if isinstance(decision, int):
            name = payload["tools"][0]["function"]["name"]
            message = {"tool_calls": [{"id": f"provider-call-{decision}", "type": "function",
                "function": {"name": name, "arguments": json_module.dumps({"index": decision})}}]}
        else:
            message = {"content": decision}
        if state.after_response:
            state.after_response()
        return SimpleNamespace(raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": message, "finish_reason": "stop"}]})

    monkeypatch.setattr(cloud_runtime, "_post_with_hard_wall_clock_timeout", post)

    def run(decisions, *, max_steps=3, task_control=None):
        state.decisions = list(decisions)
        return conversation_runtime.run_contextual_conversation_turn("Çalışmayı tamamla", client=client,
            provider_code="custom", model_name="test-model", db_name=str(tmp_path / "unused.db"),
            history=[], max_steps=max_steps, task_control=task_control)

    state.client, state.run = client, run
    return state


def test_native_loop_reserves_once_before_dispatch_and_finishes_after_chat_deadline(native_turn):
    result = native_turn.run([1, 2, 3, "Okumayı tamamladım."])

    assert result["success"], result
    assert result["answer"] == "Okumayı tamamladım."
    assert len(result["model_responses"]) == 4
    assert [row["deadline"] for row in native_turn.requests] == [280, 700, 700, 700]
    assert [row["timeout"] for row in native_turn.requests] == [120] * 4
    assert native_turn.reservations == [(180, {"max_steps": 3})]
    assert native_turn.executed == [(1, 700), (2, 700), (3, 700)]
    assert native_turn.clock.now == 420 > 280
    assert native_turn.client.turn_started_monotonic == 100
    assert result["runtime_plan"]["task_step_budget"] == 3
    assert result["session_state"]["active_entities"]["execution_budget"]["started_steps"] == 3


def test_native_plain_chat_keeps_normal_turn_deadline_without_task_reservation(native_turn):
    result = native_turn.run(["Merhaba."])

    assert result["success"] and result["answer"] == "Merhaba."
    assert native_turn.client.turn_deadline_monotonic == 280
    assert native_turn.reservations == native_turn.executed == []
    assert result["runtime_plan"]["task_budget_reserved"] is False
    assert "task_timeout_seconds" not in result["runtime_plan"]


def test_native_loop_keeps_a_larger_explicit_turn_bound(native_turn):
    native_turn.client.turn_timeout_seconds = 800
    result = native_turn.run([1, "Okumayı tamamladım."])

    assert result["success"], result
    assert [row["deadline"] for row in native_turn.requests] == [900, 900]
    assert native_turn.client.turn_started_monotonic == 100
    assert native_turn.client.turn_deadline_monotonic == 900


def test_pause_after_native_choice_prevents_reservation_and_tool_dispatch(native_turn):
    from AI.processors.task_control import AgentTaskControl
    control = AgentTaskControl()
    native_turn.after_response = control.request_pause

    result = native_turn.run([1], task_control=control)

    assert result["success"] and result["session_state"]["status"] == "paused"
    assert native_turn.reservations == native_turn.executed == []
    assert native_turn.client.turn_deadline_monotonic == 280


def test_native_loop_task_deadline_does_not_reset_when_more_tools_are_selected(native_turn):
    # Requests finish within their own timeout; the synthetic tool consumes
    # additional time before the next provider request reaches the shared cap.
    from AI.processors import tools
    native_turn.elapsed = 10
    original = tools.available_tools()["example.read"]
    from dataclasses import replace
    handler = original.handler

    def slow_read(**arguments):
        response = handler(**arguments)
        native_turn.clock.now += 210
        return response

    registry = {original.name: replace(original, handler=slow_read)}
    with patch.object(tools, "available_tools", return_value=registry), patch.object(tools, "registered_tools", return_value=registry):
        result = native_turn.run([1, 2, 3, "Unreachable answer."])

    assert not result["success"] and result["session_state"]["status"] == "paused"
    assert native_turn.reservations == [(110, {"max_steps": 3})]
    assert native_turn.client.turn_deadline_monotonic == 700
    assert native_turn.clock.now == 760
    assert len(native_turn.requests) == 3
    assert native_turn.requests[-1]["timeout"] == 120
    assert result["session_state"]["active_entities"]["model_loop"]["last_error"]["type"] == "CloudTurnDeadlineExceeded"
