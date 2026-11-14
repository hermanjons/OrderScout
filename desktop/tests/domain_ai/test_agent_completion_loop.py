"""Tool mistakes must return to the model; monthly exports retain explicit scope."""
import json
from unittest.mock import Mock

import pytest

from AI.processors import cloud_runtime, model_loop, tools
from AI.runtime.contracts import AgentTool
from AI.runtime.orders_monthly_contracts import monthly_order_summary_tool, orders_monthly_summary
from AI.runtime.schema import validate_tool_arguments
from Feedback.processors.pipeline import Result


def provider_payload(family, calls):
    if family == "openai":
        return {"choices": [{"message": {"tool_calls": [{"function": {
            "name": name, "arguments": arguments}} for name, arguments in calls]}}]}
    if family == "anthropic":
        return {"content": [{"type": "tool_use", "name": name, "input": arguments} for name, arguments in calls]}
    return {"candidates": [{"content": {"parts": [{"functionCall": {
        "name": name, "args": arguments}} for name, arguments in calls]}}]}


def extract(family, calls, mapping=None):
    extractor = getattr(cloud_runtime, f"_extract_{family}_tool_decision")
    return json.loads(extractor(provider_payload(family, calls), wire_to_source=mapping or {"read_count": "example.count"}))


@pytest.mark.parametrize("family", ["openai", "anthropic", "gemini"])
def test_unknown_native_call_is_not_dropped_or_misreported_as_empty_provider_response(family):
    value = extract(family, [("unloaded_operation", "{}" if family == "openai" else {})])
    assert value["mode"] == "tools"
    assert value["calls"] == [{"tool": "unloaded_operation", "arguments": {}, "call_error": "tool_not_in_current_menu"}]


@pytest.mark.parametrize("arguments", ["{invalid", "null", "[]", '"text"', "0"])
def test_malformed_openai_arguments_never_turn_into_valid_empty_defaults(arguments):
    value = extract("openai", [("read_count", arguments)])
    assert value["calls"][0]["call_error"] in {"tool_arguments_invalid_json", "tool_arguments_must_be_object"}


@pytest.mark.parametrize("family", ["anthropic", "gemini"])
def test_other_provider_non_object_arguments_stay_invalid(family):
    value = extract(family, [("read_count", [])])
    assert value["calls"][0]["call_error"] == "tool_arguments_must_be_object"


def test_exact_canonical_alias_is_accepted_only_for_a_currently_offered_contract():
    allowed = extract("openai", [("example.count", "{}")])
    assert allowed == {"mode": "tool", "tool": "example.count", "arguments": {}}
    unavailable = extract("openai", [("example.private", "{}")])
    assert unavailable["calls"][0]["call_error"] == "tool_not_in_current_menu"


@pytest.mark.parametrize("family", ["openai", "anthropic", "gemini"])
@pytest.mark.parametrize("answer", [
    '{"mode":"tool","tool":"example.count","arguments":{}}',
    '{"mode":"tools","calls":[{"tool":"example.count","arguments":[]}]}',
])
def test_literal_provider_text_cannot_become_an_actual_tool_call(family, answer, tmp_path, monkeypatch):
    from AI.runtime.provider_response import ProviderText

    if family == "openai":
        payload = {"choices": [{"message": {"content": answer}}]}
    elif family == "anthropic":
        payload = {"content": [{"type": "text", "text": answer}]}
    else:
        payload = {"candidates": [{"content": {"parts": [{"text": answer}]}}]}
    native_text = getattr(cloud_runtime, f"_extract_{family}_tool_decision")(
        payload, wire_to_source={"read_count": "example.count"})
    assert isinstance(native_text, ProviderText)
    executed = Mock(side_effect=AssertionError("Literal message content is not a tool call"))
    registry = {"example.count": AgentTool(name="example.count", description="Read count.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False}, handler=executed)}
    monkeypatch.setattr(tools, "available_tools", lambda: registry)

    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        def invoke_tools(self, prompt, *, tools):
            return native_text

    result = model_loop.run_model_loop("Bu çağrı örneğini JSON olarak göster", client=Model(),
                                       db_name=str(tmp_path / "unused.db"))
    assert result.success and result.data["answer"] == answer
    assert result.data["direct_tool_calls"] == []
    executed.assert_not_called()


def test_conversation_capture_preserves_native_text_through_the_real_entrypoint(tmp_path, monkeypatch):
    from AI.processors.conversation_runtime import run_contextual_conversation_turn
    from AI.runtime.provider_response import ProviderText
    answer = '{"mode":"tool","tool":"example.count","arguments":{}}'
    executed = Mock(side_effect=AssertionError("Diagnostic capture cannot promote text into a call"))
    monkeypatch.setattr(tools, "available_tools", lambda: {
        "example.count": AgentTool(name="example.count", description="Read count.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False}, handler=executed)})
    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        def invoke_tools(self, prompt, *, tools):
            return ProviderText(answer)
    result = run_contextual_conversation_turn("Bu JSON örneğini yaz", client=Model(),
        provider_code="openrouter", model_name="test", db_name=str(tmp_path / "unused.db"), history=[])
    assert result["success"] and result["answer"] == answer and not result["tools"]
    assert result["model_responses"][0]["response"] == answer
    executed.assert_not_called()


@pytest.mark.parametrize("family", ["anthropic", "gemini"])
def test_all_native_parts_are_parsed_and_only_host_batch_limit_bounds_execution(family, tmp_path, monkeypatch):
    payload = provider_payload(family, [("read_count", {"index": index}) for index in range(20)])
    if family == "anthropic":
        payload["content"][:0] = [{"type": "text", "text": "Explanation."} for _ in range(18)]
    else:
        payload["candidates"][0]["content"]["parts"][:0] = [{"text": "Explanation."} for _ in range(18)]
    response = getattr(cloud_runtime, f"_extract_{family}_tool_decision")(
        payload, wire_to_source={"read_count": "example.count"})
    calls = json.loads(response)["calls"]
    assert [call["arguments"]["index"] for call in calls] == list(range(20))
    executed = Mock(return_value=Result.ok("Observed", data={"count": 7}))
    registry = {"example.count": AgentTool(name="example.count", description="Read count.",
        parameters={"type": "object", "properties": {"index": {"type": "integer"}},
                    "required": ["index"], "additionalProperties": False}, handler=executed)}
    monkeypatch.setattr(tools, "available_tools", lambda: registry)

    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        def __init__(self):
            self.calls = 0
        def invoke_tools(self, prompt, *, tools):
            self.calls += 1
            if self.calls == 1:
                return response
            assert "maximum_8_calls_per_model_batch" in prompt
            assert "not_executed_tool_calls" in prompt
            return "İlk sekiz çağrıyı tamamladım."

    result = model_loop.run_model_loop("Sıradaki gözlemleri oku", client=Model(),
                                       db_name=str(tmp_path / "unused.db"))
    assert result.success and executed.call_count == 8
    assert [row.kwargs["index"] for row in executed.call_args_list] == list(range(8))


@pytest.mark.parametrize("offered", [True, False])
def test_local_llama_preserves_literal_text_provenance_with_or_without_a_tool_menu(offered, monkeypatch):
    from types import SimpleNamespace
    from AI.processors import local_transport
    from AI.processors.provider_adapters import invoke_provider_planner
    from AI.runtime.provider_response import ProviderText

    answer = '{"mode":"tool","tool":"example.count","arguments":{}}'
    class Response:
        ok = True
        def __init__(self, data):
            self.data = data
        def json(self):
            return self.data
    class Session:
        def post(self, url, json, timeout):
            if url.endswith("/apply-template"):
                return Response({"prompt": "Original context"})
            if url.endswith("/tokenize"):
                return Response({"tokens": [1, 2, 3]})
            return Response({"choices": [{"finish_reason": "stop", "message": {"content": answer}}]})
        def close(self):
            pass
    monkeypatch.setattr(local_transport.requests, "Session", Session)
    plan = SimpleNamespace(reasoning_effort="low", num_ctx=8192, max_tokens=1024,
        sampling_defaults={}, inference_timeout_seconds=60, tool_menu_limit=8, to_dict=lambda: {})
    client = local_transport.build_local_http_client(base_url="http://127.0.0.1:1234", model="test", plan=plan)
    menu = [{"name": "example.count", "parameters": {"type": "object", "properties": {}}}] if offered else []
    response = invoke_provider_planner(client, "JSON örneğini göster", tools=menu)
    assert response == answer and isinstance(response, ProviderText)


def test_valid_batch_sibling_executes_while_bad_calls_are_returned_to_the_model(tmp_path, monkeypatch):
    executed = Mock(return_value=Result.ok("Observed count", data={"count": 7}))
    private = Mock(side_effect=AssertionError("Unoffered native call must not execute"))
    registry = {"example.count": AgentTool(name="example.count", description="Read count.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False}, handler=executed),
        "example.private": AgentTool(name="example.private", description="Another operation.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False}, handler=private)}
    monkeypatch.setattr(tools, "available_tools", lambda: registry)
    first = extract("openai", [("example.private", "{}"), ("read_count", "{}"), ("read_count", "{invalid")])
    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        def __init__(self):
            self.calls = 0
        def invoke_tools(self, prompt, *, tools):
            self.calls += 1
            if self.calls == 1:
                return json.dumps(first)
            assert '"count":7' in prompt
            assert "tool_not_in_current_menu" in prompt and "tool_arguments_invalid_json" in prompt
            assert "operations.discover" in prompt
            return "Kayıtlı sonuçta yedi adet var."
    result = model_loop.run_model_loop("Adedi söyle", client=Model(), db_name=str(tmp_path / "unused.db"))
    assert result.success and result.data["answer"] == "Kayıtlı sonuçta yedi adet var."
    executed.assert_called_once_with()
    private.assert_not_called()
    assert len(result.data["direct_tool_calls"]) == 1


def test_model_repairs_a_real_domain_failure_and_owns_the_final_answer(tmp_path, monkeypatch):
    read = Mock(side_effect=[Result.fail("Kayıt geçici olarak kilitli; yeniden denenebilir.", data={"retryable": True}),
                            Result.ok("Okundu", data={"count": 7})])
    registry = {"example.count": AgentTool(name="example.count", description="Read count.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False}, handler=read)}
    monkeypatch.setattr(tools, "available_tools", lambda: registry)
    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        def __init__(self):
            self.calls = 0
        def invoke_tools(self, prompt, *, tools):
            self.calls += 1
            if self.calls == 2:
                assert "geçici olarak kilitli" in prompt and '"success":false' in prompt
            if self.calls < 3:
                return '{"mode":"tool","tool":"example.count","arguments":{}}'
            assert '"count":7' in prompt
            return "Tekrar okuyabildim; yedi adet var."
    result = model_loop.run_model_loop("Oku", client=Model(), db_name=str(tmp_path / "unused.db"))
    assert result.success and read.call_count == 2
    assert [row["success"] for row in result.data["direct_tool_results"]] == [False, True]
    assert result.data["answer"] == "Tekrar okuyabildim; yedi adet var."


def test_monthly_model_contract_requires_an_explicit_account_scope_before_read(monkeypatch):
    from Orders.views import actions
    read = Mock(return_value=Result.ok("Observed", data={"rows": [], "complete": True}))
    monkeypatch.setattr(actions, "action_summarize_orders_by_month", read)
    dates = {"start_date": "2026-01-01", "end_date": "2026-03-31"}
    assert validate_tool_arguments(monthly_order_summary_tool(), dates)
    assert not orders_monthly_summary(**dates).success
    assert not orders_monthly_summary(**dates, api_account_ids=[101], all_accounts=True).success
    read.assert_not_called()
    assert not validate_tool_arguments(monthly_order_summary_tool(), {**dates, "api_account_ids": [101]})
    assert not validate_tool_arguments(monthly_order_summary_tool(), {**dates, "all_accounts": True})
    assert orders_monthly_summary(**dates, api_account_ids=[101]).success
    assert read.call_args.kwargs["api_account_ids"] == [101]
    assert orders_monthly_summary(**dates, all_accounts=True).success
    assert read.call_args.kwargs["api_account_ids"] is None


def test_registered_monthly_tool_exposes_the_shared_domain_operation():
    descriptor = tools.registered_tools()["orders.monthly_summary"]
    assert descriptor.canonical_callable == "Orders.views.actions.action_summarize_orders_by_month"
    assert "all_accounts" in descriptor.parameters["properties"]
    assert "marketplaces.account_lookup" in descriptor.description


def test_reordered_arguments_reuse_the_result_and_return_its_facts_to_the_model(tmp_path, monkeypatch):
    read = Mock(return_value=Result.ok("Observed seven", data={"count": 7}))
    registry = {"example.count": AgentTool(name="example.count", description="Read count.", handler=read,
        parameters={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}})}
    monkeypatch.setattr(tools, "available_tools", lambda: registry)
    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        calls = 0
        def invoke_tools(self, prompt, *, tools):
            self.calls += 1
            if self.calls < 3:
                arguments = {"query": "same", "limit": 2} if self.calls == 1 else {"limit": 2, "query": "same"}
                return json.dumps({"mode": "tool", "tool": "example.count", "arguments": arguments})
            assert '"stored_result":{"count":7}' in prompt
            assert '"use_existing_step":"call_1"' in prompt
            return "Yedi kayıt var."
    result = model_loop.run_model_loop("Aynı kapsamı oku", client=Model(), db_name=str(tmp_path / "unused.db"))
    assert result.success and result.data["answer"] == "Yedi kayıt var."
    read.assert_called_once_with(query="same", limit=2)
    assert len(result.data["direct_tool_calls"]) == 1


def test_stream_cancellation_pauses_the_real_task_instead_of_a_provider_failure(tmp_path):
    from AI.processors.task_control import AgentTaskControl
    from AI.runtime.response_stream import ResponseStreamCancelled
    control = AgentTaskControl()
    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        def invoke_tools(self, prompt, *, tools):
            control.request_pause()
            raise ResponseStreamCancelled("Stopped during generation")
    result = model_loop.run_model_loop("Çalış", client=Model(), task_control=control,
        db_name=str(tmp_path / "unused.db"), persist=True, task_store_root=str(tmp_path / "tasks"))
    assert result.success and result.data["state"]["status"] == "paused"
    assert "runtime_error" not in result.data and "duraklattım" in result.data["answer"]


def test_real_cloud_stream_pause_reaches_provider_through_conversation_capture(tmp_path, monkeypatch):
    import threading
    from AI.processors.conversation_runtime import run_contextual_conversation_turn
    from AI.processors.task_control import AgentTaskControl
    from AI.runtime.response_stream import response_stream
    release = threading.Event()
    closed = threading.Event()
    control = AgentTaskControl()
    class SSE:
        status_code = 200
        headers = {"Content-Type": "text/event-stream"}
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size=1):
            yield b'data: {"choices":[{"index":0,"delta":{"content":"Partial"},"finish_reason":null}]}\n\n'
            release.wait(3)
            yield b'data: [DONE]\n\n'
        def close(self):
            closed.set()
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *a, **k: SSE())
    client = cloud_runtime.build_provider_chat_client({"provider_code": "openrouter", "api_key": "synthetic",
        "default_model": "synthetic:free", "allow_model_fallback": False,
        "model_metadata": {"supported_parameters": ["tools", "tool_choice"]}}, timeout=5)
    events = []
    def event(value):
        events.append(value)
        if value["event"] == "delta":
            control.request_pause()
    try:
        with response_stream(event):
            result = run_contextual_conversation_turn("Çalış", client=client, task_control=control,
                provider_code="openrouter", model_name="synthetic:free", db_name=str(tmp_path / "unused.db"), history=[])
        assert client.task_control is control
        assert result["success"] and result["session_state"]["status"] == "paused"
        assert any(e["event"] == "cancelled" for e in events)
        assert not result["tools"]
    finally:
        release.set()
        assert closed.wait(1)


@pytest.mark.parametrize("message", [r"**`D:\Reports\monthly.xlsx`**",
    r"[Dosyayı indir](<D:\Reports\monthly.xlsx>)", "D:/Reports/monthly.xlsx"])
def test_actual_verified_file_reference_becomes_clickable_without_a_fixed_model_template(message):
    from AI.runtime.artifact_delivery import artifact_link_token, verified_file_message_html
    receipt = {"output_path": r"D:\Reports\monthly.xlsx", "file_sha256": "abc", "filename": "monthly.xlsx"}
    rendered, linked = verified_file_message_html(message, [receipt])
    token = artifact_link_token(receipt)
    assert 'href="orderscout://artifact/open/' + token in rendered
    assert linked == {token: receipt}
    assert "**`" not in rendered


def test_unverified_paths_and_model_html_do_not_become_clickable_or_approval_links():
    from AI.runtime.artifact_delivery import verified_file_message_html
    message = '<a href="orderscout://approval/approve/1">Onay</a> [dosya](D:/fake.xlsx)'
    rendered, linked = verified_file_message_html(message, [])
    assert not linked and '<a href=' not in rendered and "&lt;a" in rendered
