"""UI and headless entrypoints share the model-owned conversation contract.

Ordinary turns no longer invoke an intent classifier or answer projection;
the former intent-JSON replay now exercises the actual model/tool loop.
"""
from copy import deepcopy
import json

import pytest

from AI.processors import conversation_runtime, model_loop
from AI.processors.session_state import AgentSessionState
from AI.views import chat_tab
from Feedback.processors.pipeline import Result
from Testing.processors.business_agent_fixtures import seed_business_fixture


class RecordedModel:
    runtime_name = "recorded_test"
    model_name = "recorded-model"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []
        self.resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}

    def invoke_tools(self, prompt, *, tools):
        self.prompts.append(prompt)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    def __call__(self, *args, **kwargs):
        pytest.fail("Native model adapter must be used")


def call(name, **arguments):
    return {"mode": "tool", "tool": name, "arguments": arguments}


@pytest.fixture
def run_pair(tmp_path, monkeypatch):
    database = str(tmp_path / "parity.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    monkeypatch.setattr(chat_tab, "DB_NAME", database)
    monkeypatch.setattr(chat_tab.ai_actions, "action_get_provider_account", lambda *a: Result.ok("recorded", data={
        "record": {"id": 43, "provider_code": "test", "default_model": RecordedModel.model_name}}))
    def unexpected(*args, **kwargs):
        pytest.fail("Normal conversation entered the retired interpreter/router")
    monkeypatch.setattr(chat_tab, "interpret_agent_turn", unexpected)
    monkeypatch.setattr(conversation_runtime, "interpret_agent_turn", unexpected)
    monkeypatch.setattr(chat_tab, "_task_domain_requested", unexpected)

    def run(message, responses, state=None):
        ui_client, headless_client = RecordedModel(responses), RecordedModel(responses)
        monkeypatch.setattr(chat_tab, "build_provider_chat_client", lambda *a, **k: ui_client)
        ui = chat_tab._run_chat_turn_with_runtime(message, source="cloud", runtime_record={"id": 43},
                                                history=[], session_state=deepcopy(state))
        history = []
        headless = conversation_runtime.run_contextual_conversation_turn(message, client=headless_client,
            provider_code="test", model_name=RecordedModel.model_name, db_name=database, history=history,
            session_state=deepcopy(state))
        assert ui.success == headless["success"]
        assert ui.data["answer"] == headless["answer"]
        assert ui.data["decision_path"] == headless["decision_path"] == model_loop.ENGINE
        assert ui.data["tool_names"] == headless["tools"]
        ui_state, other_state = ui.data["state"], headless["session_state"]
        for key in ("active_domain", "status", "active_scopes", "active_pending_action_id"):
            assert ui_state[key] == other_state[key], key
        assert history[-1]["content"] == ui.data["answer"]
        for candidate in (ui_state, other_state):
            assert [turn["role"] for turn in candidate["conversation_turns"]][-2:] == ["user", "assistant"]
        assert len(ui_client.prompts) == len(headless_client.prompts)
        return ui, headless
    return run


@pytest.mark.parametrize("message,answer", [
    ("Nasılsın başkan?", "İyiyim başkan, senden ne haber?"),
    ("Ne yapabilirsin?", "Kayıtlarını inceleyip uygun araçlarla rapor hazırlayabilirim."),
    ("Hangi mağazayı kastettiğimi bilmiyorsan sor", "Hangi mağazayı incelememi istersin?"),
])
def test_natural_answer_is_shared_and_never_replaced_by_a_template(run_pair, message, answer):
    ui, headless = run_pair(message, [answer])
    assert ui.success and not headless["tools"]
    assert ui.data["response_synthesis"]["prose_reviewed"] is False


def test_native_orders_source_and_scope_are_same_in_both_entrypoints(run_pair):
    ui, headless = run_pair("Kayıtlı siparişleri oku", [call("orders.summary", period="all"), "Kayıtlı 6 sipariş var."])
    assert ui.success and headless["tools"] == ["orders.summary"]
    assert ui.data["direct_tool_results"][0]["data"]["total_orders"] == 6
    assert headless["tool_results"][0]["data"]["total_orders"] == 6


def test_native_profit_scalar_count_is_safe_through_both_entrypoints(run_pair):
    ui, headless = run_pair("Kârı incele", [call("finance.profit_estimate", period="all"), "Eksik maliyetlerden ötürü tam kâr hesaplanamıyor."])
    assert ui.success and headless["tools"] == ["finance.profit_estimate"]
    assert ui.data["direct_tool_results"][0]["data"]["orders"] == 6


def test_model_can_repair_an_unknown_tool_without_legacy_business_routing(run_pair):
    ui, headless = run_pair("Hesaba bak", [call("nonexistent.operation"), call("accounts.health"), "Yerel hesap durumunu okudum."])
    assert ui.success and headless["tools"] == ["accounts.health"]


def test_next_conversation_has_fresh_receipt_after_a_failed_task(run_pair):
    state = AgentSessionState(goal="Old failed goal", status="failed").to_dict()
    state["active_entities"]["response_synthesis"] = {"candidate_accepted": False, "final_source": "old_failure"}
    ui, headless = run_pair("selam", ["Buradayım."], state)
    assert ui.success and headless["session_state"]["status"] == "complete"
    assert ui.data["response_synthesis"]["final_source"] == "model_loop_response"
    assert state["status"] == "failed"


def test_provider_failure_preserves_task_without_fake_business_success(run_pair):
    ui, headless = run_pair("Siparişleri oku", [RuntimeError("provider unavailable")])
    assert not ui.success and not headless["success"] and not headless["tools"]
    assert ui.data["runtime_error"]["phase"] == "provider"


def test_ordinary_model_json_is_content_and_cannot_become_an_intent_or_effect(run_pair):
    content = json.dumps({"mode": "act", "domain": "stock", "objective": "Create a stock item"})
    ui, headless = run_pair("JSON örneği göster", [content])
    assert ui.success and ui.data["answer"] == content and not headless["tools"]
    assert not ui.data["approval_required"]
