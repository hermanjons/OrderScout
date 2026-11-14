"""Model-authored evidence gaps return to the actor within the existing budget."""
import json
from unittest.mock import Mock

import pytest

from AI.processors import model_loop, observation_artifacts
from AI.processors.session_state import AgentSessionState
from AI.processors.source_policy import EXISTING_ONLY
from AI.runtime.provider_response import ProviderText
from Testing.processors.order_snapshot_fixture import seed_order_snapshot_fixture


class Model:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.prompts = []
        self.resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}

    def invoke_tools(self, prompt, *, tools):
        self.prompts.append(prompt)
        decision = next(self.decisions)
        return ProviderText(decision) if isinstance(decision, str) else json.dumps(decision)


def call(tool, **arguments):
    return {"mode": "tool", "tool": tool, "arguments": arguments}


def unfinished(answer):
    return answer, {"continuation_required": True,
                    "continuation_feedback": "Diğer mağazaların kayıtlarını da okuyup toplamı doğrula."}


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(observation_artifacts, "OBSERVATION_ARTIFACTS_ROOT", tmp_path / "observations")
    path = str(tmp_path / "business.sqlite3")
    seed_order_snapshot_fixture(path, isolation_root=tmp_path)
    return path


def test_review_gap_returns_to_actor_then_real_orders_read_completes_the_answer(database, monkeypatch):
    draft = "Seçili mağazanın siparişlerini okudum; diğer mağazalar henüz doğrulanmadı."
    final = "Tüm mağazalardaki 571 sipariş kaydını okudum."
    model = Model([call("operations.discover", query="orders.snapshot", limit=1),
                   call("orders.snapshot", api_account_ids=[101]), draft,
                   call("orders.snapshot"), final])
    review = Mock(side_effect=[unfinished(draft), (final, {"continuation_required": False})])
    monkeypatch.setattr("AI.runtime.answer_review.review_answer", review)
    result = model_loop.run_model_loop("Bütün mağazaların siparişlerine bak", client=model,
                                       db_name=database, max_steps=8)
    assert result.success and result.data["answer"] == final
    reads = [row for row in result.data["direct_tool_results"] if row["tool"] == "orders.snapshot"]
    assert len(reads) == 2 and all(row["success"] for row in reads)
    assert reads[-1]["data"]["total_count"] == 571
    assert {row["api_account_id"] for row in reads[-1]["data"]["orders"]} == {101, 102}
    context = json.loads(model.prompts[3]._context.split(": ", 1)[1])
    assert context["feedback"][-1]["continuation_feedback"] == unfinished(draft)[1]["continuation_feedback"]
    state = result.data["state"]
    assert state["status"] == "complete" and state["active_entities"]["model_loop"]["review_followup_count"] == 1
    assert [row["content"] for row in state["conversation_turns"] if row["role"] == "assistant"] == [final]
    assert result.data["response_synthesis"]["candidate_accepted"]


def test_review_cannot_extend_the_tool_budget_and_keeps_last_model_candidate(database, monkeypatch):
    candidate = "Seçili mağazayı okudum; diğer mağazaların toplamı henüz doğrulanmadı."
    model = Model([call("orders.snapshot", api_account_ids=[101]), candidate])
    monkeypatch.setattr("AI.runtime.answer_review.review_answer", lambda client, state, answer, **kwargs: unfinished(answer))
    result = model_loop.run_model_loop("Bütün mağazaların siparişlerine bak", client=model,
                                       db_name=database, max_steps=1)
    assert not result.success and result.data["answer"] == candidate
    assert result.data["state"]["status"] == "interrupted"
    assert result.data["state"]["active_entities"]["execution_budget"]["started_steps"] == 1
    marker = result.data["response_synthesis"]
    assert marker["candidate_accepted"] is False and marker["final_source"] == "model_review_incomplete"
    assert marker["continuation_blocked_reason"] == "tool_budget_exhausted"
    assert len(model.prompts) == 2 and len(result.data["direct_tool_calls"]) == 1


def test_review_followups_stop_at_two_and_reset_for_the_next_user_turn(tmp_path, monkeypatch):
    candidates = ["Birinci model adayı.", "İkinci model adayı.", "Son model adayı; iş henüz tamamlanmadı."]
    model = Model(candidates)
    monkeypatch.setattr("AI.runtime.answer_review.review_answer", lambda client, state, answer, **kwargs: unfinished(answer))
    result = model_loop.run_model_loop("İşi tamamla", client=model, db_name=str(tmp_path / "unused.db"), max_steps=8)
    assert not result.success and result.data["answer"] == candidates[-1]
    assert len(model.prompts) == 3
    assert result.data["state"]["status"] == "interrupted"
    assert result.data["state"]["active_entities"]["model_loop"]["review_followup_count"] == 2
    assert result.data["response_synthesis"]["continuation_blocked_reason"] == "review_followup_limit"
    final = "Yeni talimat için modelin tamamlanmış yanıtı."
    next_model = Model(["Yeni model adayı.", final])
    monkeypatch.setattr("AI.runtime.answer_review.review_answer", Mock(side_effect=[
        unfinished("Yeni model adayı."), (final, {"continuation_required": False})]))
    next_turn = model_loop.run_model_loop("Yeni talimat", client=next_model, session_state=result.data["state"],
                                         db_name=str(tmp_path / "unused.db"), max_steps=8)
    assert next_turn.success and next_turn.data["answer"] == final
    assert next_turn.data["state"]["active_entities"]["model_loop"]["review_followup_count"] == 1


@pytest.mark.parametrize("literal", [
    '<tool_call>observations_read<arg_key>step_id</arg_key><arg_value>call_24</arg_value></tool_call>',
    '{"mode":"tool","tool":"orders.query","arguments":{"order_numbers":["LITERAL-ONLY"]}}',
])
def test_literal_xml_or_json_answer_is_unchanged_and_never_executes_tools(tmp_path, monkeypatch, literal):
    monkeypatch.setattr("AI.runtime.answer_review.review_answer", lambda client, state, answer, **kwargs: (
        answer, {"continuation_required": False}))
    result = model_loop.run_model_loop("Bu çağrı örneğini aynen göster", client=Model([literal]),
                                       db_name=str(tmp_path / "unused.db"))
    assert result.success and result.data["answer"] == literal
    assert result.data["direct_tool_calls"] == [] and result.data["direct_tool_results"] == []


def test_review_followup_cannot_expand_existing_observations_source_policy(tmp_path, monkeypatch):
    draft, final = "Yeni kaynak gerekebilir.", "Yeni kaynak okuması çalıştırılmadı."
    model = Model([draft, call("orders.snapshot"), final])
    monkeypatch.setattr("AI.runtime.answer_review.review_answer", Mock(side_effect=[
        unfinished(draft), (final, {"continuation_required": False})]))
    result = model_loop.run_model_loop("Yalnız mevcut bilgilerle yanıtla", client=model,
        db_name=str(tmp_path / "unused.db"), runtime_context={"source_policy": EXISTING_ONLY})
    assert result.success and result.data["answer"] == final
    assert result.data["direct_tool_calls"] == []
    assert "invalid_tool" in model.prompts[-1]


def test_review_followup_cannot_grant_execution_authority_to_pending_approval(tmp_path, monkeypatch):
    state = AgentSessionState(goal="Hazırlanan işlemi açıkla")
    action = state.add_pending_action({"action_type": "stock.item_update", "approval_required": True,
        "execute_enabled": True, "arguments": {"payload": {"stock_item_id": 401}}})
    draft, final = "İşlem hazır.", "Hazırlanan işlem onay bekliyor; çalıştırılmadı."
    model = Model([draft, call("execute_approved_operation", action_id=action["action_id"]), final])
    monkeypatch.setattr("AI.runtime.answer_review.review_answer", Mock(side_effect=[
        unfinished(draft), (final, {"continuation_required": False})]))
    execute = Mock(side_effect=AssertionError("A reviewer cannot approve a pending effect"))
    monkeypatch.setattr("AI.processors.operation_runtime.execute_approved_operation", execute)
    result = model_loop.run_model_loop("Hazırlanan işlemi açıkla", client=model, session_state=state,
                                       db_name=str(tmp_path / "unused.db"))
    assert result.success and result.data["answer"] == final
    assert result.data["approval_required"] and result.data["state"]["active_pending_action_id"] == action["action_id"]
    assert result.data["direct_tool_calls"] == []
    execute.assert_not_called()
