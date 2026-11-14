"""Conversation acknowledgements reach the model unless they answer an approval."""
from copy import deepcopy

import pytest

from AI.processors import conversation_runtime, model_loop, task_runtime
from AI.processors.session_state import AgentSessionState, AgentTaskStep, PendingActionSnapshot
from AI.processors.turn_service import approval_reply_protocol


class ReplyModel:
    runtime_name = "recorded_test"
    model_name = "recorded-model"

    def __init__(self):
        self.prompts = []
        self.resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}

    def invoke_tools(self, prompt, *, tools):
        self.prompts.append(prompt)
        return "Konuşmamıza devam edebiliriz."

    def __call__(self, prompt):
        pytest.fail("The actual native model turn must receive this message")


def pending_state():
    action = PendingActionSnapshot.refresh_identity({
        "action_type": "stock.action_create_manual_in_transaction",
        "status": "pending_approval", "approval_required": True, "execute_enabled": True,
        "arguments": {"payload": {"item_id": 12, "qty": 2}},
    })
    state = AgentSessionState(goal="Stok girişi", active_domain="stock", status="pending_approval")
    state.pending_actions = [action]
    state.active_pending_action_id = action["action_id"]
    return state


def conversation_turn(message, model, state, tmp_path):
    return conversation_runtime.run_contextual_conversation_turn(
        message, client=model, provider_code="test", model_name=model.model_name,
        db_name=str(tmp_path / "unused.sqlite3"), history=[], session_state=state,
    )


@pytest.mark.parametrize("message", ["Evet.", "yes", "Tamam!", "olur", "OK", "Hayır.", "dur"])
def test_bare_acknowledgements_require_a_current_pending_action(message):
    assert approval_reply_protocol(message) == ""
    assert approval_reply_protocol(message, AgentSessionState(goal="Sohbet").to_dict()) == ""
    state = pending_state()
    expected = "cancel" if message in {"Hayır.", "dur"} else "approve"
    assert approval_reply_protocol(message, state) == expected
    state.cancel_active_pending_action()
    assert approval_reply_protocol(message, state.to_dict()) == ""


@pytest.mark.parametrize("message", ["tamam", "evet", "hayır", "dur"])
def test_bare_reply_after_conversation_reaches_the_actual_model_turn(message, tmp_path, monkeypatch):
    def retired(*args, **kwargs):
        pytest.fail("An ordinary reply must not enter the retired interpreter")

    monkeypatch.setattr(conversation_runtime, "interpret_agent_turn", retired)
    state = AgentSessionState(goal="Sohbet", active_domain="general", status="complete")
    state.record_turn(role="user", content="Birlikte çalışabilir miyiz?", mode="model_loop")
    state.record_turn(role="assistant", content="Hazırım, birlikte çalışabiliriz.", mode="model_loop")
    model = ReplyModel()
    turn = conversation_turn(message, model, state.to_dict(), tmp_path)
    assert turn["success"]
    assert turn["decision_path"] == model_loop.ENGINE
    assert turn["answer"] == "Konuşmamıza devam edebiliriz."
    assert len(model.prompts) == 1
    assert "Hazırım, birlikte çalışabiliriz." in model.prompts[0]
    assert not turn["tools"]


@pytest.mark.parametrize("message,decision_path", [
    ("tamam", "acceptance_execute_disabled"),
    ("hayır", "typed_pending_action_cancel"),
])
def test_real_pending_action_keeps_exact_host_control(message, decision_path, tmp_path):
    model, state = ReplyModel(), pending_state()
    before = deepcopy(state.to_dict())
    turn = conversation_turn(message, model, state.to_dict(), tmp_path)
    assert turn["decision_path"] == decision_path
    assert not model.prompts
    assert not turn["tools"]
    assert state.to_dict() == before
    if message == "tamam":
        assert turn["session_state"]["active_pending_action_id"] == state.active_pending_action_id
    else:
        assert not turn["session_state"]["active_pending_action_id"]


@pytest.mark.parametrize("message", ["tamam", "hayır"])
def test_explicit_stale_action_identity_still_reaches_the_control_refusal(message, tmp_path):
    state, model = pending_state(), ReplyModel()
    stale_id = "a" * 64
    text = f"action_id {stale_id} {message}"
    assert approval_reply_protocol(text) == ("approve" if message == "tamam" else "cancel")
    turn = conversation_turn(text, model, state.to_dict(), tmp_path)
    assert turn["decision_path"] == "typed_control_stale_action"
    assert turn["session_state"]["active_pending_action_id"] == state.active_pending_action_id
    assert not model.prompts


def test_model_loop_resume_uses_its_own_continuation_without_interpreting_again(monkeypatch):
    state = AgentSessionState(goal="Devam eden görev", status="paused", active_domain="general")
    state.active_entities["model_loop"] = {"engine": model_loop.ENGINE}
    state.remaining_steps = [AgentTaskStep(index=1, prompt="Oku", step_id="next")]
    calls = []

    def resume(message, **kwargs):
        calls.append((message, kwargs))
        return "resumed"

    monkeypatch.setattr(model_loop, "run_model_loop", resume)
    assert task_runtime.resume_read_task(state, planner_client=ReplyModel(), db_name="unused.sqlite3") == "resumed"
    assert calls[0][0] == state.goal
    assert calls[0][1]["continuing"] is True
