"""Durable memory, bounded working sets and actual provider usage accounting."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from AI.processors import model_loop, tools
from AI.processors.conversation_memory import read_conversation, read_observations
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.processors.source_policy import EXISTING_ONLY
from AI.runtime.catalog import record_discovered_tools, select_tool_menu, tool_definitions
from AI.runtime.context_window import bounded_preview, conversation_window, json_bytes
from AI.runtime.usage import record_provider_usage


def state_with_results(count=45):
    state = AgentSessionState(goal="Önceki raporu incele")
    state.active_entities["model_loop"] = {"engine": model_loop.ENGINE}
    for index in range(count):
        state.completed_steps.append(AgentTaskStep(index=index + 1, step_id=f"call_{index + 1}",
            prompt="orders.snapshot", tool_names=["orders.snapshot"], status="completed",
            verification_status="observed", result_message="Kayıtlar okundu.",
            result_data={"tool_result": {"total": 1000, "currency": "TRY", "orders": [
                {"id": row, "note": "uzun içerik " * 500} for row in range(20)]}}))
    return state


def test_real_catalog_uses_discovery_for_schema_size_even_below_transport_limit():
    registry = {name: tool for name, tool in tools.available_tools().items()
                if name != "operations.manual_action.route"}
    assert len(registry) < 128
    state = AgentSessionState(goal="Merhaba")
    state.active_entities["model_loop"] = {}
    menu = select_tool_menu(registry, state)
    assert set(menu) == {"operations.discover", "approvals.cancel", "conversation.read", "observations.read", "marketplaces.account_lookup"}
    assert json_bytes(tool_definitions(menu)) < json_bytes(tool_definitions(registry)) / 5
    assert state.active_entities["model_loop"]["tool_menu"]["catalog_requires_discovery"]
    assert "orders.snapshot" in state.active_entities["model_loop"]["tool_menu"]["operation_names_by_domain"]["orders"]
    record_discovered_tools(state, {"operations": [{"exposed_tool_name": "orders.snapshot"}]}, registry)
    loaded = select_tool_menu(registry, state)
    assert "orders.snapshot" in loaded
    assert tool_definitions({"orders.snapshot": loaded["orders.snapshot"]}) == tool_definitions(
        {"orders.snapshot": registry["orders.snapshot"]})


def test_older_observation_retains_the_actual_query_account_filter_scope():
    state = state_with_results(count=5)
    scope = {"account_filter_applied": False, "api_account_ids": []}
    state.completed_steps[0].result_data["tool_result"]["query_scope"] = scope

    source = model_loop._sources(state)[0]

    assert source["observed_scope"]["query_scope"] == scope


def test_oversized_discovered_contract_is_available_in_full_instead_of_discovery_deadlock():
    from dataclasses import replace
    registry = tools.registered_tools()
    big = replace(registry["orders.snapshot"], description="Detailed contract. " * 2000)
    registry = {"operations.discover": registry["operations.discover"], big.name: big}
    state = AgentSessionState(goal="Inspect")
    state.active_entities["model_loop"] = {"loaded_tool_names": ["operations.discover", big.name]}
    menu = select_tool_menu(registry, state, max_schema_bytes=4000)
    assert big.name in menu
    assert tool_definitions(menu)[-1]["description"].startswith(big.description)


def test_two_tool_window_prioritizes_discovered_contract_over_optional_controls():
    registry = tools.registered_tools()
    state = AgentSessionState(goal="Read")
    state.active_entities["model_loop"] = {"loaded_tool_names": ["orders.snapshot"]}
    menu = select_tool_menu(registry, state, limit=2)
    assert set(menu) == {"operations.discover", "orders.snapshot"}


def test_large_nested_results_are_only_projected_and_keep_full_binding_source():
    state = state_with_results()
    before = deepcopy(state.to_dict())
    context = model_loop._context(state)
    assert json_bytes(context["observations"]) < 40000
    assert len(context["observations"]) == 40
    assert "result" not in context["observations"][0]
    assert state.to_dict() == before
    read = read_observations(step_id="call_1", path="tool_result.orders[19].id", runtime_context={"state": state})
    assert read.success and read.data["value"] == 19
    assert read.data["stored_source_binding"] == {"$from_step": "call_1", "path": "tool_result.orders[19].id"}


def test_bounded_preview_does_not_mutate_or_present_sample_as_complete():
    source = {"total": 99, "rows": [{"notes": "x" * 40000} for _ in range(99)]}
    projected = bounded_preview(source, max_bytes=2000)
    assert json_bytes(projected) <= 2000
    assert projected["preview_only"] and projected["full_value_stored"]
    assert len(source["rows"]) == 99 and len(source["rows"][0]["notes"]) == 40000


def test_old_repeated_turns_are_recoverable_without_being_sent_on_every_request():
    state = AgentSessionState(goal="Devam")
    for index in range(40):
        state.record_turn(role="user" if index % 2 == 0 else "assistant", content="Aynı mesaj")
    selected, omitted = conversation_window(state.conversation_turns)
    assert len(selected) == 12 and omitted == 28
    recovered = read_conversation(offset=0, limit=20, runtime_context={"state": state})
    assert recovered.success and recovered.data["total"] == 40 and recovered.data["has_more"]
    assert len({row["turn_id"] for row in recovered.data["turns"]}) == recovered.data["count"]
    assert recovered.data["count"] > 0
    assert all(row["content"] == "Aynı mesaj" for row in recovered.data["turns"])
    all_ids = [row["turn_id"] for row in recovered.data["turns"]]
    while recovered.data["has_more"]:
        recovered = read_conversation(offset=len(all_ids), limit=20, runtime_context={"state": state})
        all_ids.extend(row["turn_id"] for row in recovered.data["turns"])
    assert len(all_ids) == len(set(all_ids)) == 40


def test_long_turn_can_be_read_in_exact_chunks():
    state = AgentSessionState(goal="Devam")
    turn = state.record_turn(role="user", content="ABCD" * 10000)
    # record_turn returns the typed turn in the current state implementation.
    identity = state.conversation_turns[-1].turn_id
    first = read_conversation(turn_id=identity, max_chars=4000, runtime_context={"state": state})
    second = read_conversation(turn_id=identity, content_offset=first.data["turns"][0]["next_content_offset"],
                               max_chars=4000, runtime_context={"state": state})
    recovered = first.data["turns"][0]["content"] + second.data["turns"][0]["content"]
    assert recovered == state.conversation_turns[0].content[:len(recovered)]
    assert second.data["turns"][0]["next_content_offset"] == len(recovered)
    selected, omitted = conversation_window(state.conversation_turns, max_bytes=3000)
    assert json_bytes(selected) < 3000 and "conversation.read" in selected[0]["content"]


@pytest.mark.parametrize("path", ["__class__", "tool_result.__class__()", "tool_result[99999]", "tool_result.api_key"])
def test_memory_read_cannot_escape_result_or_read_secret_fields(path):
    state = state_with_results(1)
    state.completed_steps[0].result_data["tool_result"]["api_key"] = "must-stay-private"
    result = read_observations(step_id="call_1", path=path, runtime_context={"state": state})
    assert not result.success and "must-stay-private" not in json.dumps(result.data)


def test_memory_only_reads_current_session_and_pages_exact_stored_array():
    state = state_with_results(1)
    other = AgentSessionState(goal="Başka sohbet")
    assert not read_observations(step_id="call_1", runtime_context={"state": other}).success
    page = read_observations(step_id="call_1", path="tool_result.orders", offset=18, limit=2,
                             runtime_context={"state": state})
    assert page.success and page.data["total"] == 20 and page.data["has_more"]
    assert page.data["next_offset"] == 19
    last = read_observations(step_id="call_1", path="tool_result.orders", offset=19, limit=2,
                             runtime_context={"state": state})
    assert last.success and not last.data["has_more"]
    assert page.data["fresh_read"] is False


def test_long_stored_result_text_is_recoverable_past_the_initial_preview():
    state = state_with_results(1)
    text = "A" * 7000 + "LAST-PART-OF-STORED-TEXT"
    state.completed_steps[0].result_data["tool_result"]["notes"] = text
    result = read_observations(step_id="call_1", path="tool_result.notes", content_offset=7000,
                               max_chars=100, runtime_context={"state": state})
    assert result.success and result.data["value"] == "LAST-PART-OF-STORED-TEXT"
    assert result.data["total_chars"] == len(text) and not result.data["has_more"]


def test_memory_pages_keep_exact_visible_continuations_in_real_model_context():
    state = AgentSessionState(goal="Devam")
    state.active_entities["model_loop"] = {"engine": model_loop.ENGINE}
    original = "Türkçe🙂\n" * 2000 + "son"
    state.record_turn(role="user", content=original)
    identity = state.conversation_turns[0].turn_id
    position, recovered = 0, ""
    while position < len(original):
        result = read_conversation(turn_id=identity, content_offset=position, max_chars=8000,
                                   runtime_context={"state": state})
        assert json_bytes(result.data) < 6000
        step = AgentTaskStep(index=len(state.completed_steps) + 1, step_id=f"call_{len(state.completed_steps) + 1}",
            prompt="conversation.read", tool_names=["conversation.read"], status="completed",
            result_data={"tool_result": result.data})
        state.completed_steps.append(step)
        visible = model_loop._sources(state)[-1]["result"]["turns"][0]
        recovered += visible["content"]
        next_position = visible["next_content_offset"]
        if next_position is None:
            break
        assert next_position == position + len(visible["content"])
        position = next_position
    assert recovered == original


def test_stored_dictionary_key_pages_and_parent_reads_redact_private_values():
    state = state_with_results(1)
    state.completed_steps[0].result_data["tool_result"] = {"TOKEN": "secret", "safe": {
        "access_token": "nested-secret", "count": 5}, **{f"field_{i}": i for i in range(20)}}
    found = []
    position = 0
    while True:
        result = read_observations(step_id="call_1", offset=position, limit=5, runtime_context={"state": state})
        assert "secret" not in json.dumps(result.data)
        found.extend(result.data["returned_keys"])
        if not result.data["has_more"]:
            break
        position = result.data["next_offset"]
    assert found == ["safe", *[f"field_{i}" for i in range(20)]]


def test_model_retrieves_old_fact_in_existing_only_mode_without_fresh_query(tmp_path):
    state = state_with_results(6)
    state.record_turn(role="user", content="Raporu USD olarak istiyorum.")
    for _ in range(20):
        state.record_turn(role="assistant", content="Kayıtlı mesaj")
    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        def __init__(self):
            self.responses = iter([
                {"mode": "tool", "tool": "conversation.read", "arguments": {"query": "USD"}},
                {"mode": "tool", "tool": "observations.read", "arguments": {
                    "step_id": "call_1", "path": "tool_result.total"}},
                "Eski talebinde USD istemiştin; kayıtlı kaynakta 1000 satır var."])
        def invoke_tools(self, prompt, *, tools):
            value = next(self.responses)
            return json.dumps(value) if isinstance(value, dict) else value
    result = model_loop.run_model_loop("Kaldığımız yerden devam", client=Model(), session_state=state,
        runtime_context={"source_policy": EXISTING_ONLY}, db_name=str(tmp_path / "no-read.db"))
    assert result.success, result.data
    assert [row["tool"] for row in result.data["direct_tool_calls"]] == ["conversation.read", "observations.read"]
    assert result.data["direct_tool_results"][0]["data"]["turns"][0]["content"] == "Raporu USD olarak istiyorum."
    assert result.data["direct_tool_results"][1]["data"]["value"] == 1000
    assert len(result.data["state"]["conversation_turns"]) == 23


def test_first_user_history_seed_is_not_duplicated_and_all_old_turns_are_stored(tmp_path):
    history = [{"role": "user", "content": f"eski {index}"} for index in range(22)]
    history.append({"role": "user", "content": "yeni"})
    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        def invoke_tools(self, prompt, *, tools):
            assert prompt.to_messages()[-1]["content"].startswith("yeni\n\n")
            return "Anladım."
    result = model_loop.run_model_loop("yeni", client=Model(), history=history, history_includes_current=True,
        db_name=str(tmp_path / "unused.db"))
    turns = result.data["state"]["conversation_turns"]
    assert len(turns) == 24 and sum(row["content"] == "yeni" for row in turns) == 1
    assert result.data["state"]["active_entities"]["model_loop"]["last_input_size"]["measurement"] == "utf8_bytes_not_tokens"


def test_identical_prior_user_message_is_preserved_when_history_excludes_new_request(tmp_path):
    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
        def invoke_tools(self, prompt, *, tools):
            return "İkinci isteğini aldım."
    result = model_loop.run_model_loop("Tekrar", client=Model(), history=[{"role": "user", "content": "Tekrar"}],
                                       db_name=str(tmp_path / "unused.db"))
    assert [row["content"] for row in result.data["state"]["conversation_turns"]] == ["Tekrar", "Tekrar", "İkinci isteğini aldım."]


@pytest.mark.parametrize("family,usage,expected", [
    ("openai", {"prompt_tokens": 80000, "completion_tokens": 200, "cost": .01,
                "prompt_tokens_details": {"cached_tokens": 70000}}, (80000, 200, 70000)),
    ("anthropic", {"input_tokens": 20, "output_tokens": 30, "cache_read_input_tokens": 40,
                   "cache_creation_input_tokens": 50}, (110, 30, 40)),
    ("gemini", {"promptTokenCount": 800, "candidatesTokenCount": 20,
                "cachedContentTokenCount": 400, "thoughtsTokenCount": 300}, (800, 320, 400)),
])
def test_provider_usage_accounts_every_response_without_storing_prompt_values(family, usage, expected):
    client = SimpleNamespace(resource_plan={})
    response = {"usageMetadata" if family == "gemini" else "usage": usage}
    for _ in range(2):
        record_provider_usage(client, {"model": "test", "messages": [{"content": "private conversation"}]},
                              response, family=family)
    row = client.resource_plan["last_provider_usage"]
    assert (row["input_tokens"], row["output_tokens"], row["cached_input_tokens"]) == expected
    totals = client.resource_plan["provider_usage_totals"]
    assert totals["input_tokens"] == expected[0] * 2 and totals["response_count"] == 2
    assert "private conversation" not in json.dumps(client.resource_plan)


def test_missing_provider_usage_is_unknown_instead_of_zero():
    client = SimpleNamespace(resource_plan={})
    record_provider_usage(client, {}, {}, family="openai")
    assert client.resource_plan["last_provider_usage"]["input_tokens"] is None
    assert "input_tokens" not in client.resource_plan["provider_usage_totals"]


@pytest.mark.parametrize("family", ["openai", "anthropic", "gemini"])
def test_actual_transport_records_provider_tokens_per_request_without_network(family, monkeypatch):
    from AI.processors import cloud_runtime
    bodies = []
    responses = {
        "openai": {"choices": [{"message": {"content": "Yanıt"}}], "usage": {
            "prompt_tokens": 8000, "completion_tokens": 25}},
        "anthropic": {"content": [{"type": "text", "text": "Yanıt"}], "usage": {
            "input_tokens": 8000, "output_tokens": 25}},
        "gemini": {"candidates": [{"content": {"parts": [{"text": "Yanıt"}]}}], "usageMetadata": {
            "promptTokenCount": 8000, "candidatesTokenCount": 25}},
    }
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return responses[family]
    def post(*args, **kwargs):
        bodies.append(kwargs["json"])
        return Response()
    monkeypatch.setattr(cloud_runtime, "_post_with_hard_wall_clock_timeout", post)
    common = {"base_url": "https://provider.invalid/v1", "api_key": "test-only", "timeout": 5}
    if family == "openai":
        client = cloud_runtime.build_openai_compatible_client(model="test-model", **common)
    elif family == "anthropic":
        client = cloud_runtime._build_anthropic_client(model="test-model", **common)
    else:
        client = cloud_runtime._build_gemini_client(model="gemini-2.5-flash", **common)
    assert client("İstek") == "Yanıt"
    assert client("Devam") == "Yanıt"
    assert len(bodies) == 2
    assert client.resource_plan["provider_usage_totals"]["input_tokens"] == 16000
    assert client.resource_plan["provider_usage_totals"]["response_count"] == 2


def test_empty_response_retry_is_included_in_actual_token_total(monkeypatch):
    from AI.processors import cloud_runtime
    responses = iter([
        {"choices": [{"message": {"content": ""}}], "usage": {"prompt_tokens": 8000, "completion_tokens": 5}},
        {"choices": [{"message": {"content": "Tamamlandı"}}], "usage": {"prompt_tokens": 8000, "completion_tokens": 20}},
    ])
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return next(responses)
    monkeypatch.setattr(cloud_runtime, "_post_with_hard_wall_clock_timeout", lambda *a, **k: Response())
    client = cloud_runtime.build_openai_compatible_client(base_url="https://provider.invalid/v1", api_key="test-only",
                                                        model="test-model", timeout=5)
    assert client("Devam") == "Tamamlandı"
    assert client.resource_plan["provider_usage_totals"]["input_tokens"] == 16000
    assert client.resource_plan["provider_usage_totals"]["response_count"] == 2
