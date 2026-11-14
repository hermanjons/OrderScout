"""Recover real wire failures without executing partial calls or losing usage."""
from __future__ import annotations

from copy import deepcopy
import json
import threading

import pytest
import requests

from AI.processors import cloud_runtime
from AI.processors.provider_adapters import normalize_provider_error
from AI.processors.task_control import AgentTaskControl
from AI.runtime.prompt import ModelPrompt
from AI.runtime.provider_response import ProviderText
from AI.runtime.response_stream import (
    ResponseStreamCancelled, ResponseStreamIncomplete, read_provider_stream, response_stream,
)


def event(payload):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return ("data: " + data + "\n\n").encode()


def choice(*, text="", tool_arguments=None, finish=None, usage=None):
    delta = {"content": text}
    if tool_arguments is not None:
        delta["tool_calls"] = [{"index": 0, "id": "synthetic-call", "type": "function",
                                "function": {"name": "orders_count", "arguments": tool_arguments}}]
    value = {"model": "synthetic:free", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        value["usage"] = usage
    return value


class Stream:
    url = "https://provider.test/v1/chat/completions"
    headers = {"Content-Type": "text/event-stream"}
    ok = True

    def __init__(self, parts):
        self.parts = parts
        self.closed = threading.Event()

    def iter_content(self, chunk_size=1):
        yield from self.parts() if callable(self.parts) else self.parts

    def close(self):
        self.closed.set()

    def raise_for_status(self):
        pass


class Buffered:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


TOOLS = [{"name": "orders.count", "description": "Read a synthetic count",
          "parameters": {"type": "object", "properties": {"period": {"type": "string"}}}}]


def client(**kwargs):
    metadata = {"supported_parameters": ["tools", "reasoning"]}
    metadata.update(kwargs.pop("model_metadata", {}))
    return cloud_runtime.build_openai_compatible_client(
        base_url="https://provider.test/v1", api_key="synthetic", model="synthetic:free",
        provider_code="openrouter", timeout=2, model_metadata=metadata, **kwargs,
    )


def install_responses(monkeypatch, responses):
    responses, sent = iter(responses), []

    def post(*args, **kwargs):
        sent.append(deepcopy(kwargs["json"]))
        return next(responses)

    monkeypatch.setattr(cloud_runtime.requests, "post", post)
    return sent


def test_native_terminal_without_done_retains_tool_and_repeated_finish_usage(monkeypatch):
    sent = install_responses(monkeypatch, [Stream([
        event(choice(tool_arguments='{"period":"all"}', finish="tool_calls")),
        event(choice(finish="tool_calls", usage={"prompt_tokens": 13, "completion_tokens": 4})),
    ])])
    runtime, events = client(), []
    with response_stream(events.append):
        answer = runtime.invoke_tools("Synthetic count", tools=TOOLS)
    assert json.loads(answer) == {"mode": "tool", "tool": "orders.count", "arguments": {"period": "all"}}
    assert len(sent) == 1
    assert [item["event"] for item in events] == ["start", "end"]
    assert runtime.resource_plan["provider_usage_totals"]["input_tokens"] == 13


@pytest.mark.parametrize("failure", [requests.ConnectionError, requests.exceptions.ChunkedEncodingError, requests.exceptions.ReadTimeout])
def test_accounting_trailer_socket_failure_preserves_completed_native_call(monkeypatch, failure):
    def parts():
        yield event(choice(tool_arguments='{"period":"all"}', finish="tool_calls"))
        raise failure("Synthetic accounting trailer disconnected")

    sent = install_responses(monkeypatch, [Stream(parts)])
    runtime = client()
    with response_stream(lambda item: None):
        answer = runtime.invoke_tools("Synthetic count", tools=TOOLS)
    assert json.loads(answer)["arguments"] == {"period": "all"} and len(sent) == 1
    assert runtime.resource_plan["provider_stream_notes"][0]["reason"] == "accounting_trailer_interrupted"
    assert runtime.resource_plan["last_provider_usage"]["usage_reported"] is False
    assert "cost_usd" not in runtime.resource_plan["provider_usage_totals"]


@pytest.mark.parametrize("trailer", [event("invalid JSON"), event({"error": {"code": 401, "message": "Synthetic error after finish"}})])
def test_error_or_malformed_trailer_cannot_be_hidden_by_native_finish(monkeypatch, trailer):
    sent = install_responses(monkeypatch, [Stream([
        event(choice(tool_arguments='{"period":"untrusted"}', finish="tool_calls")), trailer,
    ]) for _ in range(2)])
    runtime = client()
    with response_stream(lambda item: None), pytest.raises(requests.RequestException):
        runtime.invoke_tools("Synthetic count", tools=TOOLS)
    assert len(sent) <= 2
    assert runtime.resource_plan["final_model_response_received"] is False
    assert runtime.resource_plan.get("provider_stream_notes") is None


def test_complete_json_without_terminal_is_discarded_before_same_model_retry(monkeypatch):
    sent = install_responses(monkeypatch, [
        Stream([event(choice(tool_arguments='{"period":"untrusted"}', usage={"prompt_tokens": 10, "completion_tokens": 2}))]),
        Stream([event(choice(tool_arguments='{"period":"all"}', finish="tool_calls", usage={"prompt_tokens": 11, "completion_tokens": 3})), event("[DONE]")]),
    ])
    extracted, original = [], cloud_runtime._extract_openai_tool_decision

    def extract(payload, **kwargs):
        extracted.append(deepcopy(payload))
        return original(payload, **kwargs)

    monkeypatch.setattr(cloud_runtime, "_extract_openai_tool_decision", extract)
    runtime, events = client(), []
    with response_stream(events.append):
        answer = runtime.invoke_tools("Synthetic count", tools=TOOLS)
    assert json.loads(answer)["arguments"] == {"period": "all"}
    assert len(extracted) == 1 and "untrusted" not in json.dumps(extracted)
    assert len(sent) == 2 and sent[0] == sent[1]
    assert [item["event"] for item in events] == ["start", "error", "start", "end"]
    totals = runtime.resource_plan["provider_usage_totals"]
    assert totals["response_count"] == 2 and totals["input_tokens"] == 21 and totals["output_tokens"] == 5


def test_exhausted_protocol_retry_records_cause_and_never_switches_model(monkeypatch):
    sent = install_responses(monkeypatch, [Stream([event(choice(text="private unfinished reply"))]) for _ in range(2)])
    runtime = client(fallback_models=["sibling:free"], fallback_model_metadata={"sibling:free": {"supported_parameters": ["tools"]}})
    with response_stream(lambda item: None), pytest.raises(ResponseStreamIncomplete):
        runtime.invoke_tools("Synthetic count", tools=TOOLS)
    assert [payload["model"] for payload in sent] == ["synthetic:free", "synthetic:free"]
    plan = runtime.resource_plan
    assert plan["final_error_category"] == "incomplete_response"
    assert plan["final_model_response_received"] is False and plan["any_model_fallback_used"] is False
    assert plan["last_incomplete_response"]["reason"] == "connection_closed"
    assert plan["last_incomplete_response"]["terminal_received"] is False
    assert len(plan["incomplete_response_history"]) == 2
    assert "private unfinished reply" not in json.dumps(plan)


def test_length_retry_expands_only_host_default_and_preserves_reasoning(monkeypatch):
    sent = install_responses(monkeypatch, [
        Stream([event(choice(tool_arguments='{"period":"truncated"}', finish="length",
                             usage={"prompt_tokens": 12, "completion_tokens": 2048, "cost": 0.002})), event("[DONE]")]),
        Stream([event(choice(tool_arguments='{"period":"all"}', finish="tool_calls",
                             usage={"prompt_tokens": 12, "completion_tokens": 50, "cost": 0.0001})), event("[DONE]")]),
    ])
    runtime = client(request_options={"reasoning": {"effort": "high", "exclude": True}})
    with response_stream(lambda item: None):
        answer = runtime.invoke_tools("Synthetic count", tools=TOOLS)
    assert json.loads(answer)["arguments"] == {"period": "all"}
    assert [payload["max_tokens"] for payload in sent] == [2048, 8192]
    assert sent[0]["messages"] == sent[1]["messages"] and sent[0]["tools"] == sent[1]["tools"]
    assert sent[0]["reasoning"] == sent[1]["reasoning"] == {"effort": "high", "exclude": True}
    plan = runtime.resource_plan
    assert plan["last_incomplete_response"]["finish_reason"] == "length"
    assert plan["same_model_retry_events"][0]["response_reason"] == "output_limit"
    totals = plan["provider_usage_totals"]
    assert totals["output_tokens"] == 2098 and totals["cost_usd"] == pytest.approx(0.0021)


@pytest.mark.parametrize("limit_key", ["max_tokens", "max_output_tokens"])
def test_explicit_output_cap_is_respected_without_identical_retry(monkeypatch, limit_key):
    sent = install_responses(monkeypatch, [Stream([event(choice(tool_arguments='{"period":', finish="length")), event("[DONE]")])])
    runtime = client(request_options={limit_key: 512})
    with response_stream(lambda item: None), pytest.raises(ResponseStreamIncomplete) as caught:
        runtime.invoke_tools("Synthetic count", tools=TOOLS)
    assert caught.value.reason == "output_limit" and len(sent) == 1
    assert sent[0]["max_tokens"] == 512
    assert runtime.resource_plan["final_error_category"] == "incomplete_response"
    assert runtime.resource_plan["same_model_retry_events"] == []


@pytest.mark.parametrize("metadata", [{"output_token_limit": 4096}, {"top_provider": {"max_completion_tokens": 4096}}])
def test_provider_completion_limit_bounds_default_budget_growth(monkeypatch, metadata):
    sent = install_responses(monkeypatch, [
        Stream([event(choice(text="partial", finish="length")), event("[DONE]")]),
        Stream([event(choice(text="Finished", finish="stop")), event("[DONE]")]),
    ])
    runtime = client(model_metadata=metadata)
    with response_stream(lambda item: None):
        assert runtime("Synthetic") == "Finished"
    assert [payload["max_tokens"] for payload in sent] == [2048, 4096]


def test_host_default_in_route_metadata_is_not_promoted_to_provider_cap():
    metadata = cloud_runtime._configured_fallback_model_metadata({"free_model_test_route": {"models": [
        {"model_id": "synthetic:free", "output_tokens": 2048, "native_tool_calling": True},
        {"model_id": "limited:free", "output_tokens": 2048, "metadata": {"output_token_limit": 1024}},
    ]}})
    assert "output_token_limit" not in metadata["synthetic:free"]
    assert metadata["limited:free"]["output_token_limit"] == 1024


def test_buffered_length_cannot_execute_complete_looking_tool_json(monkeypatch):
    calls = [
        {"id": "synthetic", "type": "function", "function": {"name": "orders_count", "arguments": '{"period":"rejected"}'}},
    ]
    sent = install_responses(monkeypatch, [
        Buffered({"choices": [{"finish_reason": "length", "message": {"tool_calls": calls}}],
                  "usage": {"prompt_tokens": 2, "completion_tokens": 2048}}),
        Buffered({"choices": [{"finish_reason": "stop", "message": {"content": "Finished"}}],
                  "usage": {"prompt_tokens": 2, "completion_tokens": 1}}),
    ])
    runtime = client()
    assert runtime.invoke_tools("Synthetic", tools=TOOLS) == "Finished"
    assert len(sent) == 2 and [payload["max_tokens"] for payload in sent] == [2048, 8192]
    assert runtime.resource_plan["last_incomplete_response"]["streamed"] is False
    assert runtime.resource_plan["provider_usage_totals"]["output_tokens"] == 2049


def test_paused_task_never_opens_another_provider_request(monkeypatch):
    sent = install_responses(monkeypatch, [])
    runtime = client()
    runtime.task_control = AgentTaskControl()
    runtime.task_control.request_pause()
    with response_stream(lambda item: None), pytest.raises(ResponseStreamCancelled):
        runtime("Synthetic")
    assert sent == []


def test_midstream_pause_keeps_reported_usage_without_late_mutation(monkeypatch):
    release = threading.Event()
    runtime, events = client(), []
    runtime.task_control = AgentTaskControl()

    def parts():
        yield event(choice(usage={"prompt_tokens": 14, "completion_tokens": 1}))
        yield event(choice(text="partial"))
        release.wait(2)
        yield event(choice(text="late", finish="stop", usage={"prompt_tokens": 99, "completion_tokens": 99}))

    wire = Stream(parts)
    sent = install_responses(monkeypatch, [wire])

    def observe(item):
        events.append(item)
        if item["event"] == "delta":
            runtime.task_control.request_pause()

    try:
        with response_stream(observe), pytest.raises(ResponseStreamCancelled):
            runtime("Synthetic")
        assert len(sent) == 1 and events[-1]["event"] == "cancelled"
        assert runtime.resource_plan["provider_usage_totals"]["input_tokens"] == 14
        before = deepcopy(runtime.resource_plan)
    finally:
        release.set()
    assert wire.closed.wait(1)
    assert runtime.resource_plan == before
    assert not any(item.get("text") == "late" for item in events)


def test_incomplete_error_is_typed_normalized_and_contains_no_response_values():
    wire = Stream([event(choice(tool_arguments='{"period":"private"', finish="length",
                               usage={"prompt_tokens": 3, "raw": "private value"})), event("[DONE]")])
    with pytest.raises(ResponseStreamIncomplete) as caught:
        read_provider_stream(wire, family="openai", emit=lambda text: None)
    normalized = normalize_provider_error("openrouter", caught.value)
    assert isinstance(caught.value, requests.RequestException)
    assert normalized.category == "incomplete_response" and normalized.retryable
    assert normalized.model_fallback_allowed is False
    evidence = {**caught.value.provider_stream_diagnostic, **caught.value.provider_stream_usage}
    assert evidence["reason"] == "output_limit" and evidence["finish_reason"] == "length"
    assert evidence["usage"] == {"prompt_tokens": 3}
    assert "private" not in json.dumps(evidence)


def test_empty_native_menu_requests_final_text_without_tool_authority(monkeypatch):
    literal = '{"mode":"tool","tool":"orders.count","arguments":{}}'
    sent = install_responses(monkeypatch, [Stream([event(choice(text=literal, finish="stop")), event("[DONE]")])])
    prompt = ModelPrompt("Answer using recorded results.", "Recorded order count: 570.",
                         conversation=[{"role": "assistant", "content": "I will inspect orders.count."}],
                         request="Classify these orders")
    runtime = client(model_metadata={"supported_parameters": ["tools", "tool_choice", "reasoning"]})
    with response_stream(lambda item: None):
        answer = runtime.invoke_tools(prompt, tools=[])
    assert answer == literal and isinstance(answer, ProviderText)
    assert len(sent) == 1 and "tools" not in sent[0]
    assert sent[0]["tool_choice"] == "none" and sent[0]["max_tokens"] == 8192
    assert sent[0]["messages"] == prompt.to_messages()
    assert runtime.resource_plan["invocation_contract_history"] == ["final_text"]
    assert "attempt" not in runtime.resource_plan["request_prompt_hashes"][0]


@pytest.mark.parametrize("reasoning", [{"effort": "high", "exclude": True}, {"effort": "max", "exclude": True},
                                       {"enabled": False}, {"max_tokens": 3000, "exclude": True}])
def test_empty_native_menu_preserves_explicit_reasoning_and_output_cap(monkeypatch, reasoning):
    sent = install_responses(monkeypatch, [Buffered({"choices": [{"finish_reason": "stop", "message": {"content": "Finished"}}]})])
    runtime = client(request_options={"max_tokens": 1024, "reasoning": reasoning},
                     model_metadata={"supported_parameters": ["tools", "tool_choice", "reasoning"]})
    assert runtime.invoke_tools("Synthetic", tools=[]) == "Finished"
    assert len(sent) == 1 and sent[0]["max_tokens"] == 1024
    assert sent[0]["reasoning"] == reasoning and sent[0]["tool_choice"] == "none"


def test_empty_native_menu_does_not_send_unadvertised_tool_choice(monkeypatch):
    sent = install_responses(monkeypatch, [Buffered({"choices": [{"message": {"content": "Finished"}}]})])
    runtime = client(model_metadata={"supported_parameters": ["tools"]})
    assert runtime.invoke_tools("Synthetic", tools=[]) == "Finished"
    assert "tool_choice" not in sent[0] and "tools" not in sent[0]


def test_empty_native_menu_rejects_provider_ignoring_disabled_tools(monkeypatch):
    sent = install_responses(monkeypatch, [Stream([
        event(choice(tool_arguments='{"period":"all"}', finish="tool_calls", usage={"completion_tokens": 30})),
        event("[DONE]"),
    ])])
    runtime = client(model_metadata={"supported_parameters": ["tools", "tool_choice"]})
    with response_stream(lambda item: None), pytest.raises(ResponseStreamIncomplete) as caught:
        runtime.invoke_tools("Synthetic", tools=[])
    assert caught.value.reason == "tools_disabled" and len(sent) == 1
    assert runtime.resource_plan["last_incomplete_response"]["reason"] == "tools_disabled"
    assert runtime.resource_plan["final_model_response_received"] is False
    assert runtime.resource_plan["provider_usage_totals"]["output_tokens"] == 30


def test_advertised_max_reasoning_remains_selected_through_client_factory(monkeypatch):
    sent = install_responses(monkeypatch, [Buffered({"choices": [{"message": {"content": "Finished"}}]})])
    runtime = cloud_runtime.build_provider_chat_client({
        "provider_code": "openrouter", "endpoint_url": "https://provider.test/v1", "api_key": "synthetic",
        "default_model": "synthetic:free", "is_enabled": True, "allow_model_fallback": False,
        "reasoning_effort": "max", "model_metadata": {
            "supported_parameters": ["tools", "tool_choice", "reasoning"],
            "reasoning": {"mandatory": True, "supported_efforts": ["max", "xhigh", "high", "low"]},
        },
    })
    assert runtime.invoke_tools("Synthetic", tools=[]) == "Finished"
    assert sent[0]["reasoning"] == {"effort": "max", "exclude": True}
    assert runtime.resource_plan["reasoning_effort"] == "max"


@pytest.mark.parametrize("siblings", [False, True])
def test_connection_loss_then_length_can_recover_with_one_budget_growth(monkeypatch, siblings):
    sent = install_responses(monkeypatch, [
        Stream([event(choice(tool_arguments='{"period":"discarded"}', usage={"prompt_tokens": 10, "completion_tokens": 12}))]),
        Stream([event(choice(tool_arguments='{"period":', finish="length", usage={"prompt_tokens": 10, "completion_tokens": 2048})), event("[DONE]")]),
        Stream([event(choice(tool_arguments='{"period":"all"}', finish="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 40})), event("[DONE]")]),
    ])
    options = {"fallback_models": ["sibling:free"]} if siblings else {}
    runtime = client(**options)
    with response_stream(lambda item: None):
        answer = runtime.invoke_tools("Synthetic count", tools=TOOLS)
    assert json.loads(answer)["arguments"] == {"period": "all"}
    assert [payload["max_tokens"] for payload in sent] == [2048, 2048, 8192]
    assert {payload["model"] for payload in sent} == {"synthetic:free"}
    assert all(payload["messages"] == sent[0]["messages"] and payload["tools"] == sent[0]["tools"] for payload in sent)
    plan = runtime.resource_plan
    assert [row["response_reason"] for row in plan["same_model_retry_events"]] == ["connection_closed", "output_limit"]
    assert [row["attempt"] for row in plan["request_prompt_hashes"]] == [1, 2, 3]
    assert plan["provider_usage_totals"]["output_tokens"] == 2100
    assert plan["provider_usage_totals"]["response_count"] == 3


@pytest.mark.parametrize("explicit_cap,provider_cap,expected", [(None, None, 8192), (2048, None, 2048), (None, 4096, 4096)])
def test_mandatory_reasoning_native_tools_start_with_sufficient_default_headroom(monkeypatch, explicit_cap, provider_cap, expected):
    sent = install_responses(monkeypatch, [Stream([
        event(choice(tool_arguments='{"period":"all"}', finish="tool_calls")), event("[DONE]"),
    ])])
    metadata = {"supported_parameters": ["tools", "reasoning"], "reasoning": {"mandatory": True}}
    if provider_cap is not None:
        metadata["output_token_limit"] = provider_cap
    options = {"reasoning": {"effort": "high", "exclude": True}}
    if explicit_cap is not None:
        options["max_tokens"] = explicit_cap
    runtime = client(model_metadata=metadata, request_options=options)
    with response_stream(lambda item: None):
        assert json.loads(runtime.invoke_tools("Synthetic", tools=TOOLS))["arguments"] == {"period": "all"}
    assert len(sent) == 1 and sent[0]["max_tokens"] == expected
    assert sent[0]["reasoning"] == options["reasoning"]


def test_mandatory_reasoning_budget_grows_only_once_with_fixed_ceiling(monkeypatch):
    sent = install_responses(monkeypatch, [Stream([
        event(choice(text="unfinished", finish="length")), event("[DONE]"),
    ]) for _ in range(2)])
    runtime = client(model_metadata={"reasoning": {"mandatory": True}})
    with response_stream(lambda item: None), pytest.raises(ResponseStreamIncomplete):
        runtime.invoke_tools("Synthetic", tools=TOOLS)
    assert [payload["max_tokens"] for payload in sent] == [8192, 16384]
    assert len(runtime.resource_plan["same_model_retry_events"]) == 1


@pytest.mark.parametrize("failure,explicit_cap,expected_timeouts", [
    ("output_limit", None, [2, 4]),
    ("connection_closed", None, [2, 2]),
    ("connection_closed", 512, [2, 2]),
    ("output_limit", 512, [2]),
])
def test_only_expanded_output_envelope_gets_more_phase_time(monkeypatch, failure, explicit_cap, expected_timeouts):
    sent = []
    def post(*args, **kwargs):
        sent.append({"timeout": kwargs["timeout"], "payload": deepcopy(kwargs["json"])})
        if len(sent) == 1:
            if failure == "connection_closed":
                raise ResponseStreamIncomplete("Synthetic interrupted reply", reason=failure)
            return Buffered({"choices": [{"finish_reason": "length", "message": {"content": "Partial"}}]})
        return Buffered({"choices": [{"finish_reason": "stop", "message": {"content": "Finished"}}]})
    monkeypatch.setattr(cloud_runtime, "_post_with_hard_wall_clock_timeout", post)
    options = {"reasoning": {"effort": "high", "exclude": True}}
    if explicit_cap is not None:
        options["max_tokens"] = explicit_cap
    runtime = client(request_options=options)

    if failure == "output_limit" and explicit_cap is not None:
        with pytest.raises(ResponseStreamIncomplete):
            runtime.invoke_tools("Synthetic final reply", tools=[])
    else:
        assert runtime.invoke_tools("Synthetic final reply", tools=[]) == "Finished"

    assert [row["timeout"] for row in sent] == expected_timeouts
    assert all(row["payload"]["reasoning"] == options["reasoning"] for row in sent)
    assert all(row["payload"]["model"] == "synthetic:free" for row in sent)
    expected_caps = ([8192, 16384] if failure == "output_limit" and explicit_cap is None
                     else [explicit_cap or 8192] * len(expected_timeouts))
    assert [row["payload"]["max_tokens"] for row in sent] == expected_caps


@pytest.mark.parametrize("elapsed,retry_timeout", [(0.5, 2.5), (3.1, None)])
def test_expanded_output_phase_cannot_extend_shared_turn_deadline(monkeypatch, elapsed, retry_timeout):
    now, sent = [100.0], []
    monkeypatch.setattr(cloud_runtime.time, "monotonic", lambda: now[0])
    def post(*args, **kwargs):
        sent.append(kwargs["timeout"])
        if len(sent) == 1:
            now[0] += elapsed
            return Buffered({"choices": [{"finish_reason": "length", "message": {"content": "Partial"}}]})
        return Buffered({"choices": [{"finish_reason": "stop", "message": {"content": "Finished"}}]})
    monkeypatch.setattr(cloud_runtime, "_post_with_hard_wall_clock_timeout", post)
    runtime = client()
    cloud_runtime.begin_provider_chat_turn(runtime, timeout=3)
    deadline = runtime.turn_deadline_monotonic

    if retry_timeout is None:
        with pytest.raises(cloud_runtime.CloudTurnDeadlineExceeded):
            runtime.invoke_tools("Synthetic final reply", tools=[])
        assert sent == [2]
    else:
        assert runtime.invoke_tools("Synthetic final reply", tools=[]) == "Finished"
        assert sent == [2, retry_timeout]
        assert runtime.resource_plan["request_timeout_turn_limited"] is True
    assert runtime.turn_deadline_monotonic == deadline == 103.0
    assert runtime.turn_timeout_seconds == runtime.resource_plan["turn_timeout_seconds"] == 3


def test_human_pause_before_expanded_output_retry_opens_no_request(monkeypatch):
    sent = []
    def post(*args, **kwargs):
        sent.append(kwargs["timeout"])
        return Buffered({"choices": [{"finish_reason": "length", "message": {"content": "Partial"}}]})
    monkeypatch.setattr(cloud_runtime, "_post_with_hard_wall_clock_timeout", post)
    runtime = client()
    runtime.task_control = AgentTaskControl()
    effective_timeout = cloud_runtime._effective_provider_request_timeout
    def pause_before_retry(client, configured_timeout, **kwargs):
        if configured_timeout > 2:
            runtime.task_control.request_pause()
        return effective_timeout(client, configured_timeout, **kwargs)
    monkeypatch.setattr(cloud_runtime, "_effective_provider_request_timeout", pause_before_retry)

    with pytest.raises(ResponseStreamCancelled):
        runtime.invoke_tools("Synthetic final reply", tools=[])
    assert sent == [2]
