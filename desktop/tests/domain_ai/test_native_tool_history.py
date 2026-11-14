"""Only actual current-turn tool decisions can become native call/result pairs."""
from copy import deepcopy
import json
import pickle

import pytest
import requests

from AI.processors import cloud_runtime, model_loop, tools
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.runtime.contracts import AgentTool
from AI.runtime.prompt import ModelPrompt, provider_prompt_fields
from AI.runtime.tool_history import arguments_hash, current_tool_exchanges
from Feedback.processors.pipeline import Result


def completed(state, index=1, *, status="completed", arguments=None, authored=True):
    args = arguments if arguments is not None else {"z": 2, "a": 1}
    step = AgentTaskStep(index=index, step_id=f"call_{index}", prompt="example.read", status=status,
        tool_names=["example.read"], arguments=deepcopy(args), result_message="Read actual values",
        result_data={"tool_result": {"count": index, "api_key": "private"}})
    state.completed_steps.append(step)
    if authored:
        state.active_entities["model_loop"].setdefault("authored_calls", []).append({
            "step_id": step.step_id, "operation_id": step.tool_names[0], "arguments_hash_version": 2,
            "arguments_sha256": arguments_hash(args), "wire_tool_name": "example_read"})
    return step


def state():
    result = AgentSessionState(goal="Count existing records")
    result.active_entities["model_loop"] = {"turn_started_step_count": 0}
    return result


def test_current_turn_replay_keeps_real_failures_and_excludes_old_or_unverifiable_steps():
    value = state()
    completed(value, 1)
    value.active_entities["model_loop"]["turn_started_step_count"] = 1
    completed(value, 2, status="failed")
    completed(value, 3, authored=False)
    altered = completed(value, 4)
    altered.arguments["a"] = 99
    exchanges = current_tool_exchanges(value, model_loop._preview)
    assert [r["step_id"] for r in exchanges] == ["call_2"]
    result = json.loads(exchanges[0]["messages"][1]["content"])
    assert result["success"] is False and result["step_id"] == "call_2"
    assert "private" not in json.dumps(exchanges)


def test_canonical_argument_hash_survives_checkpoint_key_sorting_and_ids_stay_linked():
    value = state()
    completed(value)
    restored = AgentSessionState.from_dict(json.loads(json.dumps(value.to_dict(), sort_keys=True)))
    first = current_tool_exchanges(value, model_loop._preview)
    second = current_tool_exchanges(restored, model_loop._preview)
    assert first == second
    assistant, result = first[0]["messages"]
    assert assistant["tool_calls"][0]["id"] == result["tool_call_id"]
    assert first[0]["id_origin"] == "host_replay_identity"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"z": 2, "a": 1}


def test_real_calculator_result_and_unit_survive_bounded_checkpoint_replay():
    from AI.processors.analysis_operations import calculate_observations

    counts = {"Picking": 238, "Shipped": 118, "Cancelled": 86, "ReadyToShip": 48,
              "Invoiced": 39, "Delivered": 25, "UnDeliveredAndReturned": 13,
              "UnDelivered": 2, "AtCollectionPoint": 1}
    source = {"source_id": "counts", "source_step_id": "read_counts", "operation_id": "orders.status_counts",
              "result": {"status_counts": counts, "total_orders": 570, "period": "all",
                         "account_scopes": [{"api_account_id": account, "account_name": name,
                                             "environment": "stage", "marketplace": "TRENDYOL"}
                                            for account, name in ((101, "Pilot Ana"), (102, "Pilot Yan"))],
                         "environment_by_account": {"101": "stage", "102": "stage"}}}
    result = calculate_observations(sources=[source], calculations=[{
        "calculation_id": "ready_to_ship_plus_invoiced", "operator": "add", "precision": 0,
        "operands": [{"source_id": "counts", "path": "status_counts.ReadyToShip"},
                     {"source_id": "counts", "path": "status_counts.Invoiced"}]}])
    assert result.success, result.data
    value = state()
    step = completed(value)
    step.tool_names = ["analysis.calculate"]
    value.active_entities["model_loop"]["authored_calls"][0].update(
        operation_id="analysis.calculate", wire_tool_name="analysis_calculate")
    step.result_data = {"tool_result": json.loads(json.dumps(result.data, sort_keys=True))}
    before = deepcopy(step.result_data)
    projected = json.loads(current_tool_exchanges(value, model_loop._preview)[0]["messages"][1]["content"])["result"]
    body = projected.get("preview", projected)
    calculation = body["verified_calculations"][0]
    assert calculation["result"] == "87" and calculation["unit"] == "order"
    assert calculation["expression"] == "48 + 39 = 87"
    assert step.result_data == before


@pytest.mark.parametrize("arguments", [{"password": "private"}, {"value": "x" * 5000}])
def test_sensitive_or_large_call_arguments_are_omitted_instead_of_changed(arguments):
    value = state()
    completed(value, arguments=arguments)
    assert current_tool_exchanges(value, model_loop._preview) == []


def test_replay_budget_keeps_complete_pairs_only():
    value = state()
    for index in range(1, 25):
        step = completed(value, index)
        step.result_data["tool_result"]["note"] = "n" * 5000
    exchanges = current_tool_exchanges(value, model_loop._preview, max_bytes=6000)
    assert len(json.dumps(exchanges, ensure_ascii=False, separators=(",", ":")).encode()) < 6100
    assert len(exchanges) <= 8 and exchanges[-1]["step_id"] == "call_24"
    assert all([m["role"] for m in row["messages"]] == ["assistant", "tool"] for row in exchanges)


def test_prompt_role_order_and_non_openai_projection_preserve_data_and_instruction_boundary():
    value = state()
    completed(value)
    pairs = current_tool_exchanges(value, model_loop._preview)
    prompt = ModelPrompt("Trusted instructions", "Recorded application data", [{"role": "assistant", "content": "Earlier answer"}],
                         "Current request", pairs)
    assert [row["role"] for row in prompt.to_messages()] == ["system", "assistant", "user", "assistant", "tool"]
    for copy in (deepcopy(prompt), pickle.loads(pickle.dumps(prompt)), prompt.with_instructions("\nextra")):
        assert copy.to_messages()[1:] == prompt.to_messages()[1:]
    for family in ("anthropic", "gemini"):
        wire = provider_prompt_fields(prompt, family=family)
        assert "call_1" in json.dumps(wire)
        assert "tool_call_id" not in json.dumps(wire.get("system", wire.get("systemInstruction", "")))
        assert all(row["role"] in {"user", "assistant", "model"} for row in wire.get("messages", wire.get("contents", [])))


def response(payload):
    reply = requests.Response()
    reply.status_code = 200
    reply._content = json.dumps(payload).encode()
    return reply


@pytest.mark.parametrize("max_steps", [1, 32])
def test_real_transport_replays_selected_wire_alias_and_host_result_once(tmp_path, monkeypatch, max_steps):
    ran = []
    def tool(name):
        return AgentTool(name=name, description="Read a count", domain="example", parameters={"type": "object", "properties": {}},
            handler=lambda: ran.append(name) or Result.ok("Read", data={"count": 3}))
    registry = {name: tool(name) for name in ("example.read", "example_read")}
    monkeypatch.setattr(tools, "available_tools", lambda: registry)
    sent = []
    replies = iter([{"choices": [{"message": {"tool_calls": [{"id": "original-provider-id", "type": "function",
        "function": {"name": "example_read_2", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]},
        {"choices": [{"message": {"content": "Sayımı tamamladım."}, "finish_reason": "stop"}]}])
    def post(*args, **kwargs):
        sent.append(deepcopy(kwargs["json"]))
        return response(next(replies))
    monkeypatch.setattr(cloud_runtime.requests, "post", post)
    client = cloud_runtime.build_provider_chat_client({"provider_code": "openrouter", "default_model": "synthetic-model",
        "endpoint_url": "https://synthetic.test/v1", "api_key": "synthetic", "is_enabled": True,
        "model_metadata": {"supported_parameters": ["tools"]}, "allow_model_fallback": False})
    result = model_loop.run_model_loop("Say", client=client, db_name=str(tmp_path / "unused.db"), max_steps=max_steps)
    assert result.success and ran == ["example_read"]
    assert [row["role"] for row in sent[1]["messages"]] == ["system", "user", "assistant", "tool"]
    assistant, returned = sent[1]["messages"][-2:]
    assert assistant["tool_calls"][0]["function"]["name"] == "example_read_2"
    assert assistant["tool_calls"][0]["id"] == returned["tool_call_id"] != "original-provider-id"
    assert json.loads(returned["content"])["result"]["count"] == 3
    # The native result body appears once, not again in the user context dump.
    assert '"count":3' not in sent[1]["messages"][1]["content"]
    assert result.data["state"]["completed_steps"][0]["tool_names"] == ["example_read"]


def test_legacy_continuation_starts_replay_with_new_calls_only(tmp_path, monkeypatch):
    value = state()
    completed(value)
    value.active_entities["model_loop"].pop("turn_started_step_count")
    value.active_entities["model_loop"]["authored_calls"][0].pop("arguments_hash_version")
    operation = AgentTool(name="example.read", description="Read", domain="example", parameters={"type": "object", "properties": {}},
        handler=lambda: Result.ok("Counted", data={"count": 2}))
    monkeypatch.setattr(tools, "available_tools", lambda: {operation.name: operation})
    class Model:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}, "native_tool_history_enabled": True}
        def __init__(self): self.prompts = []
        def invoke_tools(self, prompt, *, tools):
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                return json.dumps({"mode": "tool", "tool": operation.name, "arguments": {}})
            return "Tamamladım."
    model = Model()
    result = model_loop.run_model_loop(value.goal, client=model, session_state=value, continuing=True, db_name=str(tmp_path / "unused.db"))
    assert result.success
    assert not any(row["role"] == "tool" for row in model.prompts[0].to_messages())
    payloads = [json.loads(row["content"]) for row in model.prompts[1].to_messages() if row["role"] == "tool"]
    assert [row["step_id"] for row in payloads] == ["call_2"]
