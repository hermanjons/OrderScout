from __future__ import annotations

from copy import deepcopy
import json
import time
from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication

from AI.processors.chat_session_store import (
    conversation_history,
    list_chat_sessions,
    load_active_chat_session,
    save_active_chat_session,
)
from AI.processors.session_state import AgentSessionState
from AI.processors.task_store import save_agent_task_state
from AI.views.chat_tab import AITab, _format_runtime_activity, _run_chat_turn_with_runtime
from Feedback.processors.pipeline import Result


def _state(session_id="saved-chat", *, count=2, pending=False):
    state = AgentSessionState(goal="Aynı kapsamı yeniden göster", session_id=session_id, status="complete")
    state.active_entities["model_loop"] = {"engine": "model_loop_v1"}
    for _ in range(count):
        state.record_turn(role="user", content="Aynı kapsamı yeniden göster")
        state.record_turn(role="assistant", content="Saklanan kayıtlar: ORD-1, ORD-2")
    if pending:
        state.add_pending_action({
            "action_type": "orders.change_cargo_provider", "title": "Kargo değişikliği",
            "summary": "ORD-1 için hazırlanmış işlem", "order_numbers": ["ORD-1"],
            "_agent_task_session_id": session_id,
        })
        state.status = "pending_approval"
    return state


def test_snapshot_preserves_complete_repeated_history_and_context(tmp_path):
    state = _state(count=24)
    history = conversation_history(state.to_dict())
    history[1]["context"] = {"kind": "order_selection", "order_numbers": ["ORD-1", "ORD-2"]}
    state.active_entities["evidence"] = {"large_result": "x" * 50_000}
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), history, composer_text="Sıradaki talimat", path=path)

    saved = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")

    assert saved["history"] == history
    assert len(saved["history"]) == 48
    assert saved["state"] == state.to_dict()
    assert saved["composer_text"] == "Sıradaki talimat"
    assert not saved["checkpoint_recovered"]


def test_chat_list_updates_after_atomic_save_and_removal(tmp_path):
    path = tmp_path / "active.json"
    state = _state()
    history = conversation_history(state.to_dict())
    save_active_chat_session(state.to_dict(), history, path=path)
    library = tmp_path / "conversations"
    initial = list_chat_sessions(root=library)
    assert initial[0]["status"] == "complete"
    initial[0]["title"] = "Changed in caller"
    assert list_chat_sessions(root=library)[0]["title"] == history[0]["content"]

    state.status = "interrupted"
    save_active_chat_session(state.to_dict(), history, path=path)
    updated = list_chat_sessions(root=library)
    assert updated[0]["status"] == "interrupted"
    (library / f"{state.session_id}.json").unlink()
    assert list_chat_sessions(root=library) == []


def test_newer_checkpoint_resolves_stale_approval_and_restores_latest_model_history(tmp_path):
    state = _state(pending=True)
    state.updated_at = "2026-10-01T10:00:00+00:00"
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), conversation_history(state.to_dict()), path=path)
    state.cancel_active_pending_action(reason="user_cancelled", cancelled_by="user")
    state.record_turn(role="user", content="Vazgeç")
    state.record_turn(role="assistant", content="İşlem iptal edildi.")
    state.updated_at = "2026-10-02T10:00:00+00:00"
    save_agent_task_state(state, root=tmp_path / "tasks")

    saved = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")

    assert saved["checkpoint_recovered"]
    assert not saved["state"]["pending_actions"]
    assert not saved["state"]["active_pending_action_id"]
    assert saved["history"][-1] == {"role": "assistant", "content": "İşlem iptal edildi."}


def test_older_checkpoint_cannot_revive_cancelled_action(tmp_path):
    state = _state(pending=True)
    state.updated_at = "2026-10-01T10:00:00+00:00"
    save_agent_task_state(state, root=tmp_path / "tasks")
    state.cancel_active_pending_action(reason="user_cancelled", cancelled_by="user")
    state.updated_at = "2026-10-02T10:00:00+00:00"
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), conversation_history(state.to_dict()), path=path)

    saved = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")

    assert not saved["checkpoint_recovered"]
    assert not saved["state"]["pending_actions"]


def test_corrupt_or_wrong_identity_checkpoint_uses_valid_snapshot(tmp_path):
    state = _state()
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), conversation_history(state.to_dict()), path=path)
    task_dir = tmp_path / "tasks"
    task_dir.mkdir()
    checkpoint = task_dir / f"{state.session_id}.json"
    for contents in ('{"broken":', json.dumps(_state("different-session").to_dict())):
        checkpoint.write_text(contents, encoding="utf-8")
        saved = load_active_chat_session(path=path, task_store_root=task_dir)
        assert saved["state"]["session_id"] == state.session_id
        assert saved["history"] == conversation_history(state.to_dict())
        assert saved["checkpoint_error"]


def test_interrupted_work_keeps_checkpoint_and_guidance_without_replaying(tmp_path):
    state = _state()
    state.status = "running"
    state.active_entities["execution_checkpoint"] = {"phase": "tool_started", "effect_status": "unknown"}
    state.active_entities["task_control"] = {"reason": "user_revision", "queued_user_messages": ["Yalnız bugünü getir"]}
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), conversation_history(state.to_dict()), path=path)

    saved = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")

    assert saved["state"]["status"] == "interrupted"
    assert saved["state"]["active_entities"]["execution_checkpoint"]["effect_status"] == "unknown"
    assert saved["composer_text"] == "Yalnız bugünü getir"


def test_crash_before_first_checkpoint_recovers_submitted_request_without_changing_business_goal(tmp_path):
    state = _state()
    request = "Bu kez yalnız ekim ayının siparişlerini getir"
    history = [*conversation_history(state.to_dict()), {"role": "user", "content": request}]
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), history, path=path)

    saved = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")

    assert saved["recovered_user_messages"] == [request]
    assert saved["state"]["conversation_turns"][-1]["content"] == request
    assert saved["state"]["conversation_turns"][-1]["mode"] == "recovered_submission"
    assert saved["state"]["goal"] == state.goal
    assert saved["history"] == history
    save_active_chat_session(saved["state"], saved["history"], path=path)
    again = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")
    assert len(again["state"]["conversation_turns"]) == len(saved["state"]["conversation_turns"])
    assert not again["recovered_user_messages"]


def test_newer_checkpoint_consumes_submissions_positionally_and_preserves_repeated_late_guidance(tmp_path):
    state = _state()
    state.updated_at = "2026-10-01T10:00:00+00:00"
    request, guidance = "Yeni dönemi getir", "Yalnız tamamlananları getir"
    history = [*conversation_history(state.to_dict()), *[
        {"role": "user", "content": text} for text in (request, guidance, guidance)
    ]]
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), history, queued_guidance=[guidance, guidance], path=path)
    state.record_turn(role="user", content=request)
    state.record_turn(role="assistant", content="İlk okuma kaydedildi.")
    state.record_turn(role="user", content=guidance)
    state.updated_at = "2026-10-02T10:00:00+00:00"
    save_agent_task_state(state, root=tmp_path / "tasks")

    saved = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")

    assert saved["checkpoint_recovered"]
    assert saved["recovered_user_messages"] == [guidance]
    assert [row["content"] for row in saved["state"]["conversation_turns"]].count(guidance) == 2
    assert saved["history"][-2:] == [{"role": "user", "content": guidance}] * 2


def test_queued_guidance_recovery_is_stable_across_repeated_reopens(tmp_path):
    state = _state()
    guidance = "Aynı isteği yeniden incele"
    state.active_entities["task_control"] = {"reason": "user_revision", "queued_user_messages": [guidance, guidance]}
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), conversation_history(state.to_dict()), path=path)
    saved = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")
    assert saved["recovered_user_messages"] == [guidance, guidance]
    save_active_chat_session(saved["state"], saved["history"], path=path)
    again = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")
    assert not again["recovered_user_messages"]
    assert [row["content"] for row in again["state"]["conversation_turns"]].count(guidance) == 2


def test_divergent_same_session_history_requires_explicit_resubmission(tmp_path):
    state = _state()
    state.updated_at = "2026-10-01T10:00:00+00:00"
    request = "Kaydedilmemiş son isteğim"
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), [*conversation_history(state.to_dict()), {"role": "user", "content": request}], path=path)
    state.conversation_turns = []
    state.record_turn(role="user", content="Farklı kayıtlı dal")
    state.record_turn(role="assistant", content="Farklı dal yanıtı")
    state.updated_at = "2026-10-02T10:00:00+00:00"
    save_agent_task_state(state, root=tmp_path / "tasks")
    saved = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")
    assert saved["resubmit_user_messages"] == [request]
    assert saved["composer_text"] == request
    assert request not in [row["content"] for row in saved["state"]["conversation_turns"]]


@pytest.mark.parametrize("contents", ["broken", "[]", '{"version": 2}', '{"version":1,"session_state":{}}',
                                      '{"version":1,"session_state":{"session_id":"../other"}}'])
def test_malformed_active_snapshot_is_rejected_without_rewriting(tmp_path, contents):
    path = tmp_path / "active.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")
    assert path.read_text(encoding="utf-8") == contents


def test_failed_atomic_save_keeps_previous_usable_chat(tmp_path):
    state = _state()
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), conversation_history(state.to_dict()), path=path)
    previous = path.read_bytes()
    with patch("AI.processors.chat_session_store._replace_checkpoint", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError):
            save_active_chat_session(state.to_dict(), [], path=path)
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob("*.tmp"))


def test_activity_shows_actual_usage_and_does_not_invent_missing_usage():
    runtime = {"runtime_name": "test", "model_name": "selected", "resource_plan": {"provider_usage_totals": {
        "input_tokens": 8412, "output_tokens": 531, "response_count": 3, "responses_with_usage": 3,
    }}}
    text = _format_runtime_activity("cloud", runtime)
    assert "giriş 8,412, çıkış 531" in text
    assert "3 model yanıtı" in text
    assert "Token" not in _format_runtime_activity("cloud", {"resource_plan": {}})


@pytest.fixture
def tabs():
    app = QApplication.instance() or QApplication([])
    opened = []
    yield opened
    for tab in opened:
        tab.close()
        tab.deleteLater()
    app.processEvents()


def test_ui_restart_restores_full_model_context_and_approval_without_execution(tabs):
    state = _state(count=18, pending=True)
    history = conversation_history(state.to_dict())
    save_active_chat_session(state.to_dict(), history, composer_text="Sonraki sorum")
    with patch.object(AITab, "_start_approved_action_worker") as execute:
        tab = AITab()
        tabs.append(tab)
    assert tab._chat_history == history
    assert tab._conversation_state["session_id"] == state.session_id
    assert tab._pending_action_from_state()["action_id"] == state.active_pending_action_id
    assert tab.composer.toPlainText() == "Sonraki sorum"
    assert tab._approval_card_actions
    execute.assert_not_called()


def test_crash_gap_followup_reaches_actual_native_loop_with_original_submitted_request(tabs):
    state = _state()
    request = "Önceki kapsamı bırak; yalnız ekim ayının iadelerini getir"
    history = [*conversation_history(state.to_dict()), {"role": "user", "content": request}]
    save_active_chat_session(state.to_dict(), history)
    tab = AITab()
    tabs.append(tab)

    class NativeModel:
        runtime_name, model_name = "offline_test", "recorded-model"

        def __init__(self):
            self.resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
            self.prompts = []

        def invoke_tools(self, prompt, *, tools):
            self.prompts.append(prompt)
            return "Ekim ayı iadeleri isteğinden devam ediyorum."

    model = NativeModel()
    provider = {"id": 17, "provider_code": "test", "default_model": model.model_name}
    with patch("AI.views.chat_tab.ai_actions.action_get_provider_account", return_value=Result.ok("Loaded", data={"record": provider})), patch(
        "AI.views.chat_tab.build_provider_chat_client", return_value=model
    ):
        result = _run_chat_turn_with_runtime("Devam et", source="cloud", runtime_record=provider,
                                             history=tab._chat_history, session_state=tab._conversation_state)
    assert result.success
    assert len(model.prompts) == 1
    assert request in str(model.prompts[0])
    assert result.data["session_state"]["session_id"] == state.session_id
    turns = result.data["session_state"]["conversation_turns"]
    assert [row["content"] for row in turns].count(request) == 1
    assert len(turns) == len(state.conversation_turns) + 3


def test_recovering_unsaved_approval_preserves_goal_and_never_executes_it(tabs):
    state = _state(pending=True)
    history = [*conversation_history(state.to_dict()), {"role": "user", "content": "Onayla"}]
    save_active_chat_session(state.to_dict(), history)
    with patch.object(AITab, "_start_approved_action_worker") as execute:
        tab = AITab()
        tabs.append(tab)
    assert tab._conversation_state["goal"] == state.goal
    assert tab._conversation_state["conversation_turns"][-1]["content"] == "Onayla"
    assert tab._conversation_state["active_pending_action_id"] == state.active_pending_action_id
    assert tab._pending_action_from_state()["action_id"] == state.active_pending_action_id
    execute.assert_not_called()


def test_restarted_chat_sends_followup_through_real_model_loop_with_saved_turns(tabs):
    state = _state(count=18)
    saved_history = conversation_history(state.to_dict())
    save_active_chat_session(state.to_dict(), saved_history)

    class RecordedModel:
        runtime_name = "offline_test"
        model_name = "recorded-model"

        def __init__(self):
            self.resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
            self.prompts = []

        def invoke_tools(self, prompt, *, tools):
            self.prompts.append(prompt)
            return "Önceki konuşmayı koruyarak devam ediyorum."

        def __call__(self, prompt):
            pytest.fail("The native model loop must own this followup.")

    model = RecordedModel()
    tab = AITab()
    tabs.append(tab)
    tab.source_combo.blockSignals(True)
    tab.source_combo.setCurrentIndex(tab.source_combo.findData("cloud"))
    tab.source_combo.blockSignals(False)
    provider = {"id": 17, "provider_code": "test", "default_model": model.model_name}
    with patch.object(tab, "_selected_provider_record", return_value=provider), patch(
        "AI.views.chat_tab.ai_actions.action_get_provider_account", return_value=Result.ok("Loaded", data={"record": provider})
    ), patch("AI.views.chat_tab.build_provider_chat_client", return_value=model):
        tab.composer.setPlainText("Bu konuşmadan devam edelim")
        tab._send_message()
        app = QApplication.instance()
        deadline = time.monotonic() + 10
        while tab._chat_worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
    assert tab._chat_worker is None
    assert tab._last_chat_success
    assert len(model.prompts) == 1
    assert "Saklanan kayıtlar: ORD-1, ORD-2" in str(model.prompts[0])
    assert "Bu konuşmadan devam edelim" in str(model.prompts[0])
    assert len(tab._conversation_state["conversation_turns"]) == len(saved_history) + 2
    assert tab._conversation_state["session_id"] == state.session_id
    assert tab._chat_history[:-2] == saved_history
    tab.close()
    reopened = AITab()
    tabs.append(reopened)
    assert reopened._chat_history[-1]["content"] == "Önceki konuşmayı koruyarak devam ediyorum."
    assert len(reopened._chat_history) == len(saved_history) + 2


def test_switching_sessions_replaces_history_and_invalidates_old_approval_cards(tabs):
    tab = AITab()
    tabs.append(tab)
    first = _state("first-session", count=18, pending=True)
    second = _state("second-session", count=1)
    second.goal = "İkinci sohbet"
    second.conversation_turns = []
    second.record_turn(role="user", content="İkinci sohbet")
    second.record_turn(role="assistant", content="İkinci yanıt")

    tab._restore_task_chat_context({"state": first.to_dict()})
    first_cards = set(tab._approval_card_actions)
    tab._restore_task_chat_context({"state": second.to_dict()})
    assert tab._chat_history == conversation_history(second.to_dict())
    assert "ORD-1" not in tab.transcript.toPlainText()
    assert not tab._approval_card_actions
    tab._restore_task_chat_context({"state": first.to_dict()})
    assert tab._chat_history == conversation_history(first.to_dict())
    assert not first_cards.intersection(tab._approval_card_actions)
    assert "İkinci yanıt" not in tab.transcript.toPlainText()


def test_busy_work_cannot_be_replaced_by_another_session(tabs):
    tab = AITab()
    tabs.append(tab)
    before = deepcopy(tab._conversation_state)
    with patch.object(tab, "_worker_is_running", return_value=True), patch("AI.views.chat_tab.load_agent_task_state") as load:
        tab._restore_task_chat_context({"state": _state("other-session").to_dict()})
        tab._load_selected_task_session()
    assert tab._conversation_state == before
    assert not tab._chat_history
    load.assert_not_called()


def test_same_session_can_reload_a_newer_saved_turn(tabs):
    tab = AITab()
    tabs.append(tab)
    state = _state()
    tab._restore_task_chat_context({"state": state.to_dict()})
    state.record_turn(role="user", content="Yeni talimat")
    state.record_turn(role="assistant", content="Yeni kayıtlı yanıt")
    tab._restore_task_chat_context({"state": state.to_dict()})
    assert tab._chat_history == conversation_history(state.to_dict())


def test_restore_cannot_make_an_inactive_proposal_actionable(tabs):
    tab = AITab()
    tabs.append(tab)
    state = _state(pending=True).to_dict()
    old_action = deepcopy(state["pending_actions"][0])
    state["active_pending_action_id"] = "stale-unmatched-action"
    tab._restore_task_chat_context({"state": state, "approval_required": True, "action_proposal": old_action})
    assert not tab._pending_action_from_state()
    assert not tab._approval_card_actions


def test_new_chat_stays_empty_after_restart(tabs):
    tab = AITab()
    tabs.append(tab)
    tab._restore_task_chat_context({"state": _state().to_dict()})
    tab._reset_chat()
    new_id = tab._conversation_state["session_id"]
    tab.close()
    reopened = AITab()
    tabs.append(reopened)
    assert reopened._conversation_state["session_id"] == new_id
    assert not reopened._chat_history
    assert "OrderScout AI conversation" not in reopened.transcript.toPlainText()


def test_ui_does_not_overwrite_a_corrupt_snapshot_on_open_or_close(tabs):
    from AI.processors import chat_session_store
    path = chat_session_store.ACTIVE_CHAT_FILE
    path.write_text('{"incomplete":', encoding="utf-8")
    tab = AITab()
    tabs.append(tab)
    assert "Önceki sohbet açılamadı" in tab.transcript.toPlainText()
    tab.close()
    assert path.read_text(encoding="utf-8") == '{"incomplete":'


def test_recovered_revision_blocks_old_approval_until_the_new_instruction_is_processed(tmp_path):
    from AI.processors import model_loop
    state = _state(pending=True)
    history = [*conversation_history(state.to_dict()), {"role": "user", "content": "Ürün sayısını 5 olarak değiştir"}]
    path = tmp_path / "active.json"
    save_active_chat_session(state.to_dict(), history, path=path)
    saved = load_active_chat_session(path=path, task_store_root=tmp_path / "tasks")
    restored = AgentSessionState.from_dict(saved["state"])
    assert restored.goal == state.goal
    assert restored.active_pending_action_id == state.active_pending_action_id
    with patch("AI.processors.operation_runtime.execute_approved_operation") as execute:
        result = model_loop.resume_model_loop_approval(restored.to_dict(), action_id=state.active_pending_action_id,
                                                       persist=False, db_name=str(tmp_path / "unused.db"))
    assert not result.success and result.data["requires_user_revision_turn"]
    execute.assert_not_called()
