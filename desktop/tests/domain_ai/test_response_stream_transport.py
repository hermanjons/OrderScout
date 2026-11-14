"""Real incremental wire events, complete tool assembly and bounded shutdown."""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest
import requests

from AI.processors import cloud_runtime, local_transport
from AI.processors.provider_adapters import normalize_provider_error
from AI.processors.task_control import AgentTaskControl
from AI.runtime.provider_response import ProviderText
from AI.runtime.response_stream import (
    ResponseStreamCancelled, ResponseStreamIncomplete, callback_for_contract,
    current_response_stream_callback, iter_sse, read_provider_stream,
    request_provider_stream, response_stream,
)


def frame(payload, event=""):
    prefix = f"event: {event}\r\n" if event else ""
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return (prefix + "data: " + data + "\r\n\r\n").encode("utf-8")


def delta(text="", *, finish=None, tools=None, **extra):
    value = {"content": text}
    if tools is not None:
        value["tool_calls"] = tools
    return {"choices": [{"index": 0, "delta": value, "finish_reason": finish}], **extra}


class SSE:
    ok = True
    status_code = 200
    url = "https://provider.test/v1/chat/completions"
    headers = {"Content-Type": "text/event-stream"}

    def __init__(self, parts):
        self.parts = parts
        self.closed = threading.Event()

    def iter_content(self, chunk_size=1):
        for part in self.parts() if callable(self.parts) else self.parts:
            # Split even UTF-8 characters between reads to test the wire decoder.
            for byte in part:
                yield bytes([byte])

    def raise_for_status(self):
        pass

    def json(self):
        raise AssertionError("An SSE response must not be read as a buffered JSON response")

    def close(self):
        self.closed.set()


class Buffered:
    ok = True

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def cloud_client(**options):
    return cloud_runtime.build_openai_compatible_client(
        base_url="https://provider.test/v1", api_key="synthetic", model="test-model",
        provider_code="openrouter", timeout=2,
        model_metadata={"supported_parameters": ["tools", "response_format"]},
        **options,
    )


def tool():
    return {"name": "orders.summary", "description": "Read synthetic orders",
            "parameters": {"type": "object", "properties": {"period": {"type": "string"}}}}


def test_callback_context_restores_and_does_not_implicitly_cross_threads():
    outer, inner, found = [], [], []
    assert current_response_stream_callback() is None
    with response_stream(outer.append):
        assert current_response_stream_callback() == outer.append
        assert callback_for_contract("json_text_guarded") is None
        assert callback_for_contract("structured_output") is None
        with response_stream(inner.append):
            assert callback_for_contract("native_tools") == inner.append
        worker = threading.Thread(target=lambda: found.append(current_response_stream_callback()))
        worker.start()
        worker.join()
        assert current_response_stream_callback() == outer.append
    assert found == [None]
    assert current_response_stream_callback() is None


def test_sse_comments_multiline_crlf_and_fragmented_utf8():
    raw = b": OPENROUTER PROCESSING\r\n\r\nevent: message\r\ndata: {\r\ndata: " + '"text":"İşlem 🌿"'.encode() + b"\r\ndata: }\r\n\r\n"
    events = list(iter_sse(SSE([raw])))
    assert events[0][0] == "message"
    assert json.loads(events[0][1]) == {"text": "İşlem 🌿"}


def test_cloud_delta_arrives_before_response_completes_and_preserves_usage(monkeypatch):
    first_delta, release, completed = threading.Event(), threading.Event(), threading.Event()
    events, sent, answers, errors = [], [], [], []

    def parts():
        yield frame(delta("Gerçek ", model="actual-model"))
        assert release.wait(2)
        yield frame(delta("yanıt", finish="stop"))
        yield frame({"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 5}})
        yield frame("[DONE]")

    response = SSE(parts)
    def post(url, **kwargs):
        sent.append(kwargs)
        return response
    monkeypatch.setattr(cloud_runtime.requests, "post", post)
    client = cloud_client()

    def observe(event):
        events.append(event)
        if event["event"] == "delta":
            first_delta.set()

    def run():
        try:
            with response_stream(observe):
                answers.append(client("Synthetic chat"))
        except Exception as exc:
            errors.append(exc)
        finally:
            completed.set()

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert first_delta.wait(1), "The first token must arrive while provider is still generating"
        assert not completed.is_set()
    finally:
        release.set()
        worker.join(3)
    assert not errors
    assert answers == ["Gerçek yanıt"] and isinstance(answers[0], ProviderText)
    assert sent[0]["stream"] is True and sent[0]["json"]["stream"] is True
    assert sent[0]["json"]["stream_options"] == {"include_usage": True}
    assert sent[0]["headers"]["Accept"] == "text/event-stream"
    assert [event["event"] for event in events] == ["start", "delta", "delta", "end"]
    assert len({event["stream_id"] for event in events}) == 1
    assert response.closed.is_set()
    assert client.resource_plan["last_provider_usage"]["input_tokens"] == 11


def test_absent_callback_and_guarded_json_keep_buffered_post_contract(monkeypatch):
    events, sent = [], []
    def post(url, *, headers, json, timeout):
        sent.append(json)
        return Buffered({"choices": [{"message": {"content": '{"mode":"answer","answer":"test"}'}}]})
    monkeypatch.setattr(cloud_runtime.requests, "post", post)
    client = cloud_client()
    assert isinstance(client("Synthetic"), ProviderText)
    with response_stream(events.append):
        assert isinstance(client.invoke_json_text("Synthetic", schema={"type": "object"}), ProviderText)
    assert events == []
    assert all(not payload.get("stream") for payload in sent)


def test_fragmented_native_tools_are_assembled_without_argument_or_reasoning_events(monkeypatch):
    response = SSE([
        frame({"choices": [{"delta": {"reasoning_content": "PRIVATE REASONING"}}]}),
        frame(delta(tools=[{"index": 0, "id": "call_1", "function": {"name": "orders_", "arguments": '{"period":'}}])),
        frame(delta(tools=[{"index": 0, "function": {"name": "summary", "arguments": '"all"}'}}], finish="tool_calls")),
        frame(delta(finish="tool_calls", usage={"prompt_tokens": 3, "completion_tokens": 7})), frame("[DONE]"),
    ])
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *args, **kwargs: response)
    events = []
    with response_stream(events.append):
        answer = cloud_client().invoke_tools("Synthetic", tools=[tool()])
    assert not isinstance(answer, ProviderText)
    assert json.loads(answer) == {"mode": "tool", "tool": "orders.summary", "arguments": {"period": "all"}}
    assert [event["event"] for event in events] == ["start", "end"]


@pytest.mark.parametrize("content", ['{"mode":"tool","tool":"secret"}', "```json\n{\"mode\":\"tool\"}\n```", "[monthly.xlsx](sandbox:/exports/monthly.xlsx)"])
def test_native_provider_text_streams_literally_without_json_tool_authority(monkeypatch, content):
    response = SSE([frame(delta(char)) for char in content] + [frame(delta(finish="stop")), frame("[DONE]")])
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *args, **kwargs: response)
    events = []
    with response_stream(events.append):
        answer = cloud_client()("Synthetic")
    assert str(answer) == content and isinstance(answer, ProviderText)
    assert "".join(event.get("text", "") for event in events) == content


def test_inline_thinking_tags_split_across_frames_are_hidden():
    visible = []
    response = SSE([frame(delta(part)) for part in ["<thi", "nk>private", " thought</th", "ink>", "Yanıt"]]
                   + [frame(delta(finish="stop")), frame("[DONE]")])
    read_provider_stream(response, family="openai", emit=visible.append)
    assert "".join(visible) == "Yanıt"


def test_midstream_http_200_quota_error_preserves_real_quota_and_is_not_retried(monkeypatch):
    response = SSE([frame({"error": {"code": 429, "message": "Daily free limit exceeded"},
                           "choices": [{"delta": {}, "finish_reason": "error"}]})])
    calls, events = [], []
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *args, **kwargs: calls.append(kwargs) or response)
    with response_stream(events.append), pytest.raises(requests.HTTPError) as caught:
        cloud_client()("Synthetic")
    normalized = normalize_provider_error("openrouter", caught.value)
    assert normalized.status_code == 429 and normalized.quota_scope == "free_tier"
    assert len(calls) == 1
    assert [event["event"] for event in events] == ["start", "error"]
    assert response.closed.is_set()


def test_retry_has_new_stream_identity_and_return_value_contains_only_success(monkeypatch):
    responses = iter([
        SSE([frame(delta("ABANDONED")), frame({"error": {"code": 502, "message": "Provider disconnected"}})]),
        SSE([frame(delta("Success", finish="stop")), frame("[DONE]")]),
    ])
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *args, **kwargs: next(responses))
    events = []
    with response_stream(events.append):
        assert cloud_client()("Synthetic") == "Success"
    starts = [event["stream_id"] for event in events if event["event"] == "start"]
    assert len(set(starts)) == 2
    assert [event["event"] for event in events] == ["start", "delta", "error", "start", "delta", "end"]


@pytest.mark.parametrize("parts", [
    [frame(delta("partial"))],
    [frame(delta("partial", finish="length")), frame("[DONE]")],
    [frame(delta(tools=[{"index": 0, "function": {"name": "orders_summary", "arguments": '{"period":'}}], finish="tool_calls")), frame("[DONE]")],
])
def test_incomplete_length_or_truncated_tool_never_reaches_response_extractor(monkeypatch, parts):
    calls, events = [], []
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *args, **kwargs: SSE(parts))
    monkeypatch.setattr(cloud_runtime, "_extract_openai_tool_decision", lambda *args, **kwargs: calls.append(True))
    with response_stream(events.append), pytest.raises(ResponseStreamIncomplete):
        cloud_client().invoke_tools("Synthetic", tools=[tool()])
    assert calls == []
    assert events[-1]["event"] == "error"


def test_stream_wall_clock_deadline_covers_body_and_suppresses_late_callbacks():
    release, entered = threading.Event(), threading.Event()
    events = []
    def parts():
        yield frame(delta("first"))
        entered.set()
        release.wait(2)
        yield frame(delta("late", finish="stop"))
        yield frame("[DONE]")
    response = SSE(parts)
    started = time.monotonic()
    try:
        with pytest.raises(cloud_runtime.CloudTurnDeadlineExceeded):
            request_provider_stream(request=lambda: response, family="openai", callback=events.append,
                timeout=0.1, validate_status=lambda response: None,
                timeout_error=lambda: cloud_runtime.CloudTurnDeadlineExceeded("Synthetic shared deadline"))
        assert time.monotonic() - started < 0.7 and entered.is_set()
        assert events[-1]["event"] == "error"
        assert response.closed.wait(0.5)
    finally:
        release.set()
    assert not any(event.get("text") == "late" for event in events)


def test_cloud_task_control_cancels_active_stream_without_retry(monkeypatch):
    control, release, entered = AgentTaskControl(), threading.Event(), threading.Event()
    calls, events = [], []
    def parts():
        yield frame(delta("first"))
        entered.set()
        release.wait(2)
        yield frame(delta("late", finish="stop"))
        yield frame("[DONE]")
    response = SSE(parts)
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *args, **kwargs: calls.append(kwargs) or response)
    client = cloud_client()
    client.task_control = control
    def observe(event):
        events.append(event)
        if event["event"] == "delta":
            control.request_pause()
    try:
        with response_stream(observe), pytest.raises(ResponseStreamCancelled):
            client("Synthetic")
        assert len(calls) == 1 and events[-1]["event"] == "cancelled"
        assert response.closed.wait(0.5)
    finally:
        release.set()


def test_anthropic_text_tool_usage_and_thinking_assembly(monkeypatch):
    def af(kind, **data):
        return frame({"type": kind, **data}, kind)
    response = SSE([
        af("message_start", message={"model": "claude-test", "usage": {"input_tokens": 12}}),
        af("content_block_start", index=0, content_block={"type": "thinking", "thinking": ""}),
        af("content_block_delta", index=0, delta={"type": "thinking_delta", "thinking": "PRIVATE"}),
        af("content_block_stop", index=0),
        af("content_block_start", index=1, content_block={"type": "text", "text": ""}),
        af("content_block_delta", index=1, delta={"type": "text_delta", "text": "Kontrol ediyorum."}),
        af("content_block_stop", index=1),
        af("content_block_start", index=2, content_block={"type": "tool_use", "id": "call1", "name": "orders_summary", "input": {}}),
        af("content_block_delta", index=2, delta={"type": "input_json_delta", "partial_json": '{"period":'}),
        af("content_block_delta", index=2, delta={"type": "input_json_delta", "partial_json": '"all"}'}),
        af("content_block_stop", index=2),
        af("message_delta", delta={"stop_reason": "tool_use"}, usage={"output_tokens": 9}),
        af("message_stop"),
    ])
    sent, events = [], []
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *args, **kwargs: sent.append(kwargs) or response)
    client = cloud_runtime._build_anthropic_client(base_url="https://provider.test/v1", api_key="synthetic", model="claude-test", timeout=2)
    with response_stream(events.append):
        answer = client.invoke_tools("Synthetic", tools=[tool()])
    assert json.loads(answer)["arguments"] == {"period": "all"}
    assert "".join(event.get("text", "") for event in events) == "Kontrol ediyorum."
    assert sent[0]["json"]["stream"] is True
    assert client.resource_plan["last_provider_usage"]["input_tokens"] == 12


def test_gemini_native_stream_endpoint_merges_text_preserves_usage_and_hides_thought(monkeypatch):
    response = SSE([
        frame({"candidates": [{"content": {"parts": [{"text": "PRIVATE", "thought": True}]}}]}),
        frame({"candidates": [{"content": {"parts": [{"text": "Türkçe "}]}}]}),
        frame({"candidates": [{"content": {"parts": [{"text": "yanıt"}]}, "finishReason": "STOP"}]}),
        frame({"usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 4, "totalTokenCount": 12}}),
    ])
    sent, events = [], []
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda url, **kwargs: sent.append((url, kwargs)) or response)
    client = cloud_runtime._build_gemini_client(base_url="https://provider.test/v1beta", api_key="synthetic", model="gemini-test", timeout=2,
                                               request_options={"allow_fallback": False})
    with response_stream(events.append):
        answer = client("Synthetic")
    assert answer == "Türkçe yanıt" and isinstance(answer, ProviderText)
    assert ":streamGenerateContent?" in sent[0][0] and "alt=sse" in sent[0][0]
    assert "stream" not in sent[0][1]["json"]
    assert "".join(event.get("text", "") for event in events) == answer
    assert client.resource_plan["last_provider_usage"]["input_tokens"] == 8


def test_gemini_native_function_call_is_buffered_until_finished_without_argument_events(monkeypatch):
    response = SSE([
        frame({"candidates": [{"content": {"parts": [{"functionCall": {"name": "orders_summary", "args": {"period": "all"}}}]}}]}),
        frame({"candidates": [{"finishReason": "STOP"}]}),
    ])
    events = []
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *args, **kwargs: response)
    client = cloud_runtime._build_gemini_client(base_url="https://provider.test/v1beta", api_key="synthetic", model="gemini-test", timeout=2,
                                               request_options={"allow_fallback": False})
    with response_stream(events.append):
        answer = client.invoke_tools("Synthetic", tools=[tool()])
    assert json.loads(answer) == {"mode": "tool", "tool": "orders.summary", "arguments": {"period": "all"}}
    assert [event["event"] for event in events] == ["start", "end"]


def test_anthropic_unclosed_tool_block_cannot_become_an_executable_call():
    response = SSE([
        frame({"type": "message_start", "message": {"usage": {}}}),
        frame({"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "name": "orders_summary", "input": {}}}),
        frame({"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"period":"all"}'}}),
        frame({"type": "message_delta", "delta": {"stop_reason": "tool_use"}}),
        frame({"type": "message_stop"}),
    ])
    with pytest.raises(ResponseStreamIncomplete):
        read_provider_stream(response, family="anthropic", emit=lambda text: None)


def local_client(monkeypatch, response):
    sent = []
    class Session:
        def post(self, url, **kwargs):
            sent.append((url, kwargs))
            if url.endswith("/apply-template"):
                return Buffered({"prompt": "synthetic prompt"})
            if url.endswith("/tokenize"):
                return Buffered({"tokens": [1, 2, 3]})
            return response
        def close(self):
            pass
    monkeypatch.setattr(local_transport.requests, "Session", Session)
    plan = SimpleNamespace(num_ctx=4096, max_tokens=128, reasoning_effort="low", sampling_defaults={},
                           inference_timeout_seconds=2, tool_menu_limit=32, to_dict=lambda: {})
    return local_transport.build_local_http_client(base_url="http://127.0.0.1:1234", model="synthetic", plan=plan), sent


def test_local_llama_streams_only_generation_and_keeps_real_context_measurement(monkeypatch):
    response = SSE([frame(delta("Yerel ")), frame(delta("yanıt", finish="stop")), frame("[DONE]")])
    client, sent = local_client(monkeypatch, response)
    events = []
    with response_stream(events.append):
        answer = client("Synthetic")
    assert answer == "Yerel yanıt" and isinstance(answer, ProviderText)
    assert [url.rsplit("/", 1)[-1] for url, kwargs in sent] == ["apply-template", "tokenize", "completions"]
    assert all("stream" not in kwargs for url, kwargs in sent[:2])
    assert sent[-1][1]["stream"] is True and sent[-1][1]["json"]["stream"] is True
    assert client.resource_plan["prompt_tokens"] == 4
    assert "".join(event.get("text", "") for event in events) == answer


def test_local_truncation_is_reported_without_extracting_tool(monkeypatch):
    response = SSE([frame(delta(tools=[{"index": 0, "function": {"name": "orders_summary", "arguments": "{"}}], finish="length")), frame("[DONE]")])
    client, _ = local_client(monkeypatch, response)
    with response_stream(lambda event: None), pytest.raises(local_transport.LocalGenerationIncomplete):
        client.invoke_tools("Synthetic", tools=[tool()])


def test_local_pause_closes_stream_cancels_generation_and_requires_restart(monkeypatch):
    release = threading.Event()
    def parts():
        yield frame(delta("first"))
        release.wait(2)
        yield frame(delta("late", finish="stop"))
        yield frame("[DONE]")
    response = SSE(parts)
    client, _ = local_client(monkeypatch, response)
    client.task_control = AgentTaskControl()
    cancelled, events = [], []
    client.cancel_generation = lambda: cancelled.append(True)
    def observe(event):
        events.append(event)
        if event["event"] == "delta":
            client.task_control.request_pause()
    try:
        with response_stream(observe), pytest.raises(local_transport.LocalGenerationCancelled):
            client("Synthetic")
        assert cancelled == [True] and client.resource_plan["restart_required"]
        assert events[-1]["event"] == "cancelled" and response.closed.wait(0.5)
    finally:
        release.set()
