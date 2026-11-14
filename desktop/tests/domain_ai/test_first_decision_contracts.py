"""First-choice ownership survives empty menus and provider transport changes."""
import json

import pytest

from AI.processors import cloud_runtime, model_loop, provider_adapters, tools
from AI.runtime.contracts import AgentTool
from AI.runtime.prompt import ModelPrompt
from AI.processors.session_state import AgentSessionState
from Feedback.processors.pipeline import Result


class NativeModel:
    resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}

    def __init__(self, responses):
        self.responses = iter(responses)
        self.menus = []

    def invoke_tools(self, prompt, *, tools):
        self.menus.append(tools)
        return next(self.responses)

    def __call__(self, prompt):
        pytest.fail("A native conversation must not become a guarded-JSON task")


def test_native_model_can_answer_when_no_tools_are_available(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "available_tools", lambda: {})
    client = NativeModel(["Buradayım, konuşabiliriz."])
    result = model_loop.run_model_loop("selam", client=client, db_name=str(tmp_path / "unused.db"))
    assert result.success and result.data["answer"] == "Buradayım, konuşabiliriz."
    assert client.menus == [[]] and result.data["direct_tool_calls"] == []


def test_model_can_explain_results_after_its_tool_budget_is_spent(tmp_path, monkeypatch):
    tool = AgentTool(name="example.count", description="Read one count.", parameters={
        "type": "object", "properties": {}}, handler=lambda: Result.ok("Counted", data={"count": 6}))
    monkeypatch.setattr(tools, "available_tools", lambda: {tool.name: tool})
    client = NativeModel([json.dumps({"mode": "tool", "tool": tool.name, "arguments": {}}),
                          "Altı kayıt var."])
    result = model_loop.run_model_loop("Sayısını oku", client=client, db_name=str(tmp_path / "unused.db"), max_steps=1)
    assert result.success and result.data["answer"] == "Altı kayıt var."
    assert len(client.menus[0]) == 1 and client.menus[1] == []
    assert result.data["direct_tool_results"][0]["data"]["count"] == 6


def test_guarded_json_keeps_host_instructions_separate_from_context():
    prompt = ModelPrompt("Trusted host instruction", "User request and untrusted observations")
    schema = {"type": "object", "required": ["answer"]}
    guarded = provider_adapters.guarded_json_prompt(prompt, schema)
    assert isinstance(guarded, ModelPrompt)
    messages = guarded.to_messages()
    assert messages[1] == prompt.to_messages()[1]
    assert "GUARDED JSON RESPONSE CONTRACT" in messages[0]["content"]
    assert provider_adapters.guarded_json_prompt(guarded, schema) == guarded


def test_actual_request_and_prior_speakers_reach_the_first_model_call(tmp_path):
    state = AgentSessionState(goal="Bir kavram açıkla", status="complete")
    state.record_turn(role="user", content="Agentic ne demek?", mode="model_loop")
    state.record_turn(role="assistant", content="İstersen örnek vereyim.", mode="model_loop")
    captured = []

    class InspectModel(NativeModel):
        def invoke_tools(self, prompt, *, tools):
            captured.append(prompt)
            return "Bir örnekle açıklayayım."

    result = model_loop.run_model_loop("olur", client=InspectModel([]), session_state=state,
                                       db_name=str(tmp_path / "unused.db"))
    assert result.success
    messages = captured[0].to_messages()
    assert [row["role"] for row in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "Agentic ne demek?"
    assert messages[2]["content"] == "İstersen örnek vereyim."
    assert messages[-1]["content"].startswith("olur\n\nRecorded application context")


def test_adding_contract_preserves_conversation_and_current_request():
    import pickle
    from copy import deepcopy
    prompt = ModelPrompt("Host", "Observations", [{"role": "assistant", "content": "Örnek vereyim mi?"}], "olur")
    guarded = provider_adapters.guarded_json_prompt(prompt, {"type": "object"})
    assert guarded.to_messages()[1:] == prompt.to_messages()[1:]
    assert deepcopy(guarded).to_messages() == guarded.to_messages()
    assert pickle.loads(pickle.dumps(guarded)).to_messages() == guarded.to_messages()


def test_guarded_decision_keeps_roles_and_exposes_tools_on_first_call(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "available_tools", lambda: {})
    captured = []

    class GuardedModel:
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": False}}

        def invoke_json_text(self, prompt, *, schema):
            captured.append(prompt)
            return '{"answer":"Anladım.","tool":"","arguments_json":"{}"}'

    result = model_loop.run_model_loop("Sadece konuşalım", client=GuardedModel(),
                                       db_name=str(tmp_path / "unused.db"))
    assert result.success
    assert isinstance(captured[0], ModelPrompt)
    assert "Tools: []" in captured[0].to_messages()[0]["content"]
    assert "Sadece konuşalım" in captured[0].to_messages()[1]["content"]


@pytest.mark.parametrize("family", ["openai", "anthropic", "gemini"])
def test_provider_wire_preserves_model_prompt_roles_without_network(family, monkeypatch):
    payloads = []
    responses = {
        "openai": {"choices": [{"message": {"content": "Yanıt"}}]},
        "anthropic": {"content": [{"type": "text", "text": "Yanıt"}]},
        "gemini": {"candidates": [{"content": {"parts": [{"text": "Yanıt"}]}}]},
    }

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return responses[family]

    def post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return Response()

    monkeypatch.setattr(cloud_runtime, "_post_with_hard_wall_clock_timeout", post)
    common = {"base_url": "https://provider.invalid/v1", "api_key": "test-only", "timeout": 5}
    if family == "openai":
        client = cloud_runtime.build_openai_compatible_client(model="test-model", **common)
    elif family == "anthropic":
        client = cloud_runtime._build_anthropic_client(model="test-model", **common)
    else:
        client = cloud_runtime._build_gemini_client(model="gemini-2.5-flash", **common)
    prompt = ModelPrompt("Trusted host instruction", "User request and untrusted observations")
    assert client.invoke_tools(prompt, tools=[]) == "Yanıt"
    body = payloads[0]
    if family == "openai":
        assert body["messages"] == prompt.to_messages()
    elif family == "anthropic":
        assert body["system"] == "Trusted host instruction"
        assert body["messages"] == [prompt.to_messages()[1]]
    else:
        assert body["systemInstruction"] == {"parts": [{"text": "Trusted host instruction"}]}
        assert body["contents"] == [{"role": "user", "parts": [{"text": prompt.to_messages()[1]["content"]}]}]
    assert "tools" not in body and "response_format" not in body
