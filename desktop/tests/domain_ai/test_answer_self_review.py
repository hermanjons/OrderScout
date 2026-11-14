"""A model can correct its prose from real receipts without a host template."""
import json

import pytest

from AI.processors import model_loop, tools
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.runtime.answer_review import review_answer, review_sources
from AI.runtime.response_stream import ResponseStreamCancelled, current_response_stream_callback, response_stream
from Testing.processors.order_snapshot_fixture import seed_order_snapshot_fixture


class Reviewer:
    def __init__(self, result):
        self.result, self.prompts = result, []
        self.resource_plan = {"final_answer_review_enabled": True,
                              "capability_profile": {"native_tool_runtime_enabled": True}}
    def invoke_final_text(self, prompt, *, exact_model=False):
        assert exact_model is True and callable(current_response_stream_callback())
        current_response_stream_callback()({"event": "delta", "text": "Review draft must stay invisible"})
        self.prompts.append(prompt)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def source_state():
    state = AgentSessionState(goal="Siparişleri sınıflandır")
    state.completed_steps.append(AgentTaskStep(index=1, step_id="call_1", prompt="orders.status_counts",
        tool_names=["orders.status_counts"], arguments={"period": "all", "api_account_ids": [7]},
        status="completed", result_data={"tool_result": {"total_orders": 570,
            "status_counts": {"ReadyToShip": 48, "Invoiced": 39, "Picking": 483},
            "environment_by_account": {"7": "stage"}, "account_scopes": [{"api_account_id": 7}],
            "api_key": "never-send-this", "nested": {"access_token": "nor-this"}}}))
    return state


def test_model_corrects_arithmetic_and_uses_exact_scope_without_streaming_second_draft():
    client = Reviewer("Yerel test kayıtlarında sevkiyata hazır veya faturalandırılmış 87 sipariş var.")
    original = "Sevkiyata hazır veya faturalandırılmış 46 sipariş var."
    with response_stream(lambda event: pytest.fail("Reviewer draft must not append to primary stream")):
        answer, review = review_answer(client, source_state(), original, sanitize=model_loop._preview)
    assert "87" in answer and "46" not in answer
    assert review["prose_reviewed"] and review["review_changed"]
    assert review["review_status"] == "model_self_review" and "verified" not in review
    prompt = client.prompts[0]
    assert '"ReadyToShip":48' in prompt and '"Invoiced":39' in prompt
    assert '"api_account_ids":[7]' in prompt and '"7":"stage"' in prompt
    assert "never-send-this" not in prompt and "nor-this" not in prompt
    assert prompt.to_messages()[0]["role"] == "system"


def test_review_failure_preserves_complete_model_answer():
    original = "570 sipariş var."
    answer, review = review_answer(Reviewer(RuntimeError("do not persist raw provider body")), source_state(),
                                   original, sanitize=model_loop._preview)
    assert answer == original and review["prose_reviewed"] is False
    assert review["review_status"] == "unavailable"
    assert "raw provider" not in json.dumps(review)


def test_stop_propagates_instead_of_returning_a_late_review():
    with pytest.raises(ResponseStreamCancelled):
        review_answer(Reviewer(ResponseStreamCancelled()), source_state(), "570 sipariş var.", sanitize=model_loop._preview)


def test_no_extra_model_invocation_without_numeric_evidence_or_opt_in():
    client = Reviewer("should not run")
    state = source_state()
    for text, evidence in (("Merhaba başkan.", state), ("570 sipariş olabilir.", AgentSessionState(goal="Siparişler"))):
        assert review_answer(client, evidence, text, sanitize=model_loop._preview) == (text, {"prose_reviewed": False})
    client.resource_plan["final_answer_review_enabled"] = False
    review_answer(client, state, "570 sipariş var.", sanitize=model_loop._preview)
    assert not client.prompts


def test_receipts_stay_bounded_and_failed_or_navigation_results_are_not_facts():
    state = source_state()
    for index in range(2, 42):
        step = AgentTaskStep(index=index, step_id=f"call_{index}", prompt="orders.query",
            tool_names=["orders.query"], status="completed", result_data={"tool_result": {
                "count": 570, "rows": [{"text": "x" * 1000}] * 100, "map": {"a": 1, "b": 2}}})
        state.completed_steps.append(step)
    state.completed_steps[-1].status = "failed"
    state.completed_steps[-2].tool_names = ["observations.read"]
    rows = review_sources(state, model_loop._preview)
    assert len(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()) < 21000
    assert {"call_40", "call_41"}.isdisjoint({r["step_id"] for r in rows})
    assert all("rows" not in r.get("compact_facts", {}) for r in rows)


def test_real_domain_receipts_reach_review_and_corrected_prose_is_persisted(tmp_path, monkeypatch):
    db = str(tmp_path / "orders.sqlite3")
    seed_order_snapshot_fixture(db, isolation_root=tmp_path)
    registry = tools.available_tools()
    monkeypatch.setattr(tools, "available_tools", lambda: {"orders.status_counts": registry["orders.status_counts"]})
    class Model(Reviewer):
        def __init__(self):
            super().__init__("Sipariş durumlarını yerel kayıtlardan sınıflandırdım: toplam 571 sipariş.")
            self.decisions = iter([json.dumps({"mode": "tool", "tool": "orders.status_counts", "arguments": {"period": "all"}}),
                                   "Toplam 17 sipariş."])
        def invoke_tools(self, prompt, *, tools):
            return next(self.decisions)
    model = Model()
    result = model_loop.run_model_loop("Siparişleri sınıflandır", client=model, db_name=db, persist=False)
    assert result.success and result.data["answer"] == model.result
    assert len(result.data["direct_tool_calls"]) == 1 and len(model.prompts) == 1
    assert '"total_orders":571' in model.prompts[0]
    assert result.data["state"]["conversation_turns"][-1]["content"] == model.result
    synthesis = result.data["response_synthesis"]
    assert synthesis["prose_reviewed"] and synthesis["review_changed"]
    assert synthesis["final_projection_verified"] is False


def test_real_review_uses_silent_stream_and_keeps_outer_ui_observer_quiet(monkeypatch):
    from AI.processors import cloud_runtime
    sent = []
    class Stream:
        status_code, ok = 200, True
        headers = {"Content-Type": "text/event-stream"}
        url = "https://synthetic.test/v1/chat/completions"
        def raise_for_status(self): pass
        def close(self): pass
        def iter_content(self, chunk_size=1):
            yield ("data: " + json.dumps({"model": "selected", "choices": [{"index": 0,
                "delta": {"content": json.dumps({"decision": "answer", "feedback": ""})}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10}}) + "\n\n").encode()
            yield b"data: [DONE]\n\n"
    def post(*args, **kwargs):
        sent.append(kwargs)
        return Stream()
    monkeypatch.setattr(cloud_runtime.requests, "post", post)
    client = cloud_runtime.build_provider_chat_client({"provider_code": "openrouter", "default_model": "selected",
        "endpoint_url": "https://synthetic.test/v1", "api_key": "synthetic", "is_enabled": True,
        "model_metadata": {"supported_parameters": ["tools"]}, "allow_model_fallback": False})
    outer_events = []
    candidate = "Hazır veya faturalandırılmış 87 sipariş var."
    with response_stream(outer_events.append):
        answer, marker = review_answer(client, source_state(), candidate, sanitize=model_loop._preview)
    assert marker["prose_reviewed"] and answer == candidate, json.dumps(marker)
    assert outer_events == [] and sent[0]["stream"] is True
    assert sent[0]["json"]["model"] == "selected"
